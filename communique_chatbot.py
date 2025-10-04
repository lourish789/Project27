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
from langchain.prompts import PromptTemplate
from PyPDF2 import PdfReader
import requests
from io import BytesIO
from bs4 import BeautifulSoup
import time

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
    source_type = db.Column(db.String(50), default='pdf')  # pdf, article, database
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

# Content Extraction Functions
def scrape_communique_article(url):
    """Scrape article content from Communiqué"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract title
        title = soup.find('h1')
        title_text = title.get_text(strip=True) if title else ""
        
        # Extract article content (adjust selectors based on actual site structure)
        article_body = soup.find('article') or soup.find('div', class_='post-content')
        
        if article_body:
            # Remove script and style elements
            for script in article_body(["script", "style"]):
                script.decompose()
            
            text = article_body.get_text(separator='\n', strip=True)
            return f"{title_text}\n\n{text}"
        
        return ""
    except Exception as e:
        print(f"Error scraping article: {str(e)}")
        return None

def download_pdf(url):
    """Download PDF from URL"""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return BytesIO(response.content)
    except Exception as e:
        print(f"Error downloading PDF: {str(e)}")
        return None

def extract_text_from_pdf(pdf_file):
    """Extract text from PDF"""
    try:
        pdf_reader = PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text
    except Exception as e:
        print(f"Error extracting PDF text: {str(e)}")
        return None

def process_and_embed_document(url, filename, source_type='pdf'):
    """Process document/article and embed in Pinecone"""
    try:
        # Extract text based on source type
        if source_type == 'article':
            text = scrape_communique_article(url)
        elif source_type == 'pdf':
            pdf_file = download_pdf(url)
            if pdf_file:
                text = extract_text_from_pdf(pdf_file)
            else:
                return False
        else:
            return False
        
        if not text or len(text.strip()) < 100:
            print(f"Insufficient content extracted from {url}")
            return False
        
        # Split text into chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        chunks = text_splitter.split_text(text)
        
        # Create metadata
        metadatas = [
            {
                "source": filename,
                "url": url,
                "chunk": i,
                "type": source_type
            } for i in range(len(chunks))
        ]
        
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
        
        print(f"Successfully embedded {len(chunks)} chunks from {filename}")
        return True
    except Exception as e:
        print(f"Error processing document: {str(e)}")
        return False

def get_conversational_chain(user_id):
    """Create conversational chain with memory and custom prompt"""
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
    
    # Custom prompt for Africa Creative Economy context
    custom_prompt = PromptTemplate(
        input_variables=["context", "question"],
        template="""You are an expert assistant specializing in Africa's creative economy, 
drawing insights from Communiqué's African Creative Economy Database and related resources.

Context from the database:
{context}

Question: {question}

Provide detailed, accurate information about Africa's creative industries including:
- Film & TV (Nollywood, Riverwood, production houses, streaming platforms)
- Music (labels, festivals, streaming platforms)
- Fashion (designers, brands, African styles)
- Gaming (developers, esports, platforms)
- Creator Economy (digital platforms, tools)
- Media (publishers, digital outlets)
- Creative Arts (galleries, theater, art collectives)
- Cultural Heritage (museums, heritage institutions)

Include relevant statistics, organizations, investors, events, and policy insights when available.
If you mention specific entities or data, cite the source from the context.

Answer:"""
    )
    
    # Create conversational chain
    llm = ChatOpenAI(
        temperature=0.7,
        model_name="gpt-4",
        openai_api_key=os.environ.get('OPENAI_API_KEY')
    )
    
    chain = ConversationalRetrievalChain.from_llm(
        llm=llm,
        retriever=vectorstore.as_retriever(search_kwargs={"k": 5}),
        memory=memory,
        return_source_documents=True,
        verbose=True,
        combine_docs_chain_kwargs={"prompt": custom_prompt}
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
    source_type = data.get('source_type', 'pdf')  # pdf, article, database
    
    if not url or not filename:
        return jsonify({'message': 'URL and filename required'}), 400
    
    # Check if document already exists
    existing = Document.query.filter_by(url=url).first()
    if existing:
        return jsonify({'message': 'Document already exists', 'id': existing.id}), 200
    
    # Save document
    document = Document(filename=filename, url=url, source_type=source_type)
    db.session.add(document)
    db.session.commit()
    
    # Process document
    success = process_and_embed_document(url, filename, source_type)
    
    if success:
        document.processed = True
        db.session.commit()
        return jsonify({
            'message': 'Document processed successfully',
            'id': document.id
        }), 200
    else:
        return jsonify({'message': 'Error processing document'}), 500

@app.route('/api/documents/bulk-add', methods=['POST'])
@token_required
def bulk_add_documents(current_user):
    """Bulk add multiple Communiqué articles"""
    data = request.json
    documents = data.get('documents', [])
    
    results = []
    for doc in documents:
        url = doc.get('url')
        filename = doc.get('filename')
        source_type = doc.get('source_type', 'article')
        
        if not url or not filename:
            continue
        
        # Check if exists
        existing = Document.query.filter_by(url=url).first()
        if existing:
            results.append({'url': url, 'status': 'exists'})
            continue
        
        # Save and process
        document = Document(filename=filename, url=url, source_type=source_type)
        db.session.add(document)
        db.session.commit()
        
        success = process_and_embed_document(url, filename, source_type)
        
        if success:
            document.processed = True
            db.session.commit()
            results.append({'url': url, 'status': 'success'})
        else:
            results.append({'url': url, 'status': 'failed'})
        
        time.sleep(1)  # Rate limiting
    
    return jsonify({'results': results}), 200

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
        
        # Format sources
        sources = []
        for doc in result.get('source_documents', []):
            sources.append({
                'source': doc.metadata.get('source', 'Unknown'),
                'url': doc.metadata.get('url', ''),
                'type': doc.metadata.get('type', 'unknown'),
                'content': doc.page_content[:200] + '...'
            })
        
        return jsonify({
            'response': response,
            'sources': sources
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
        'source_type': doc.source_type,
        'processed': doc.processed,
        'uploaded_at': doc.uploaded_at.isoformat()
    } for doc in documents])

@app.route('/api/stats', methods=['GET'])
@token_required
def get_stats(current_user):
    """Get statistics about the knowledge base"""
    total_docs = Document.query.count()
    processed_docs = Document.query.filter_by(processed=True).count()
    user_conversations = Conversation.query.filter_by(user_id=current_user.id).count()
    
    return jsonify({
        'total_documents': total_docs,
        'processed_documents': processed_docs,
        'user_conversations': user_conversations
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
