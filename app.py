import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from datetime import datetime, timedelta
from functools import wraps
from pinecone import Pinecone, ServerlessSpec
from langchain.embeddings import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores import Pinecone as LangchainPinecone
from langchain.chains import ConversationalRetrievalChain
from langchain.chat_models import ChatOpenAI
from langchain.memory import ConversationBufferMemory
from PyPDF2 import PdfReader
import requests
from io import BytesIO

app = Flask(__name__)
CORS(app)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///chatbot.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Initialize Pinecone
pc = Pinecone(api_key=os.environ.get('PINECONE_API_KEY'))
index_name = "africa-creative-economy"

# Initialize embeddings
embeddings = OpenAIEmbeddings(openai_api_key=os.environ.get('OPENAI_API_KEY'))

# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255))
    google_id = db.Column(db.String(255), unique=True)
    name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    conversations = db.relationship('Conversation', backref='user', lazy=True)

class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    url = db.Column(db.Text, nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed = db.Column(db.Boolean, default=False)

# Create tables
with app.app_context():
    db.create_all()

# JWT Token decorator
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'message': 'Token is missing'}), 401
        try:
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            current_user = User.query.get(data['user_id'])
        except:
            return jsonify({'message': 'Token is invalid'}), 401
        return f(current_user, *args, **kwargs)
    return decorated

# RAG Helper Functions
def download_pdf(url):
    """Download PDF from URL"""
    response = requests.get(url)
    return BytesIO(response.content)

def extract_text_from_pdf(pdf_file):
    """Extract text from PDF"""
    pdf_reader = PdfReader(pdf_file)
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text()
    return text

def process_and_embed_document(url, filename):
    """Process PDF and embed in Pinecone"""
    try:
        # Download and extract text
        pdf_file = download_pdf(url)
        text = extract_text_from_pdf(pdf_file)
        
        # Split text into chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len
        )
        chunks = text_splitter.split_text(text)
        
        # Create metadata
        metadatas = [{"source": filename, "chunk": i} for i in range(len(chunks))]
        
        # Check if index exists, create if not
        if index_name not in pc.list_indexes().names():
            pc.create_index(
                name=index_name,
                dimension=1536,
                metric='cosine',
                spec=ServerlessSpec(cloud='aws', region='us-east-1')
            )
        
        # Embed and store in Pinecone
        vectorstore = LangchainPinecone.from_texts(
            chunks,
            embeddings,
            index_name=index_name,
            metadatas=metadatas
        )
        
        return True
    except Exception as e:
        print(f"Error processing document: {str(e)}")
        return False

def get_conversational_chain(user_id):
    """Create conversational chain with memory"""
    # Get user's conversation history
    history = Conversation.query.filter_by(user_id=user_id).order_by(
        Conversation.timestamp.desc()
    ).limit(10).all()
    
    # Initialize memory
    memory = ConversationBufferMemory(
        memory_key="chat_history",
        return_messages=True,
        output_key='answer'
    )
    
    # Load previous conversations into memory
    for conv in reversed(history):
        memory.chat_memory.add_user_message(conv.message)
        memory.chat_memory.add_ai_message(conv.response)
    
    # Create vectorstore
    vectorstore = LangchainPinecone.from_existing_index(
        index_name=index_name,
        embedding=embeddings
    )
    
    # Create conversational chain
    llm = ChatOpenAI(
        temperature=0.7,
        model_name="gpt-4",
        openai_api_key=os.environ.get('OPENAI_API_KEY')
    )
    
    chain = ConversationalRetrievalChain.from_llm(
        llm=llm,
        retriever=vectorstore.as_retriever(search_kwargs={"k": 3}),
        memory=memory,
        return_source_documents=True,
        verbose=True
    )
    
    return chain

# Routes
@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.json
    
    if User.query.filter_by(email=data['email']).first():
        return jsonify({'message': 'User already exists'}), 400
    
    hashed_password = generate_password_hash(data['password'])
    new_user = User(
        email=data['email'],
        password_hash=hashed_password,
        name=data.get('name', '')
    )
    
    db.session.add(new_user)
    db.session.commit()
    
    token = jwt.encode({
        'user_id': new_user.id,
        'exp': datetime.utcnow() + timedelta(days=30)
    }, app.config['SECRET_KEY'])
    
    return jsonify({
        'token': token,
        'user': {
            'id': new_user.id,
            'email': new_user.email,
            'name': new_user.name
        }
    }), 201

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(email=data['email']).first()
    
    if not user or not check_password_hash(user.password_hash, data['password']):
        return jsonify({'message': 'Invalid credentials'}), 401
    
    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.utcnow() + timedelta(days=30)
    }, app.config['SECRET_KEY'])
    
    return jsonify({
        'token': token,
        'user': {
            'id': user.id,
            'email': user.email,
            'name': user.name
        }
    })

@app.route('/api/auth/google', methods=['POST'])
def google_auth():
    data = request.json
    google_id = data.get('google_id')
    email = data.get('email')
    name = data.get('name')
    
    user = User.query.filter_by(google_id=google_id).first()
    
    if not user:
        user = User(
            email=email,
            google_id=google_id,
            name=name
        )
        db.session.add(user)
        db.session.commit()
    
    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.utcnow() + timedelta(days=30)
    }, app.config['SECRET_KEY'])
    
    return jsonify({
        'token': token,
        'user': {
            'id': user.id,
            'email': user.email,
            'name': user.name
        }
    })

@app.route('/api/documents/add', methods=['POST'])
@token_required
def add_document(current_user):
    data = request.json
    url = data.get('url')
    filename = data.get('filename')
    
    if not url or not filename:
        return jsonify({'message': 'URL and filename required'}), 400
    
    # Save document
    document = Document(filename=filename, url=url)
    db.session.add(document)
    db.session.commit()
    
    # Process in background (in production, use Celery)
    success = process_and_embed_document(url, filename)
    
    if success:
        document.processed = True
        db.session.commit()
        return jsonify({'message': 'Document processed successfully'}), 200
    else:
        return jsonify({'message': 'Error processing document'}), 500

@app.route('/api/chat', methods=['POST'])
@token_required
def chat(current_user):
    data = request.json
    message = data.get('message')
    
    if not message:
        return jsonify({'message': 'Message required'}), 400
    
    try:
        # Get conversational chain with user history
        chain = get_conversational_chain(current_user.id)
        
        # Get response
        result = chain({"question": message})
        response = result['answer']
        
        # Save conversation
        conversation = Conversation(
            user_id=current_user.id,
            message=message,
            response=response
        )
        db.session.add(conversation)
        db.session.commit()
        
        return jsonify({
            'response': response,
            'sources': [doc.metadata for doc in result.get('source_documents', [])]
        })
    
    except Exception as e:
        return jsonify({'message': f'Error: {str(e)}'}), 500

@app.route('/api/history', methods=['GET'])
@token_required
def get_history(current_user):
    conversations = Conversation.query.filter_by(
        user_id=current_user.id
    ).order_by(Conversation.timestamp.desc()).limit(50).all()
    
    return jsonify([{
        'id': conv.id,
        'message': conv.message,
        'response': conv.response,
        'timestamp': conv.timestamp.isoformat()
    } for conv in conversations])

@app.route('/api/documents', methods=['GET'])
@token_required
def get_documents(current_user):
    documents = Document.query.all()
    return jsonify([{
        'id': doc.id,
        'filename': doc.filename,
        'url': doc.url,
        'processed': doc.processed,
        'uploaded_at': doc.uploaded_at.isoformat()
    } for doc in documents])

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
