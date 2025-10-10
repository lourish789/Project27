from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from agentic_rag import AgenticRAGAgent
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Initialize the agent
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

agent = AgenticRAGAgent(
    openai_api_key=OPENAI_API_KEY,
    pinecone_api_key=PINECONE_API_KEY
)

# Store conversation history (in production, use Redis or database)
conversations = {}

@app.route('/')
def home():
    """Serve the frontend"""
    return render_template('index.html')

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Render"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat()
    })

@app.route('/api/chat', methods=['POST'])
def chat():
    """Main chat endpoint"""
    try:
        data = request.json
        query = data.get('query', '').strip()
        session_id = data.get('session_id', 'default')
        
        if not query:
            return jsonify({'error': 'Query is required'}), 400
        
        # Get or create conversation history
        if session_id not in conversations:
            conversations[session_id] = []
        
        conversation_history = conversations[session_id]
        
        # Process the query
        result = agent.process_query(query, conversation_history)
        
        # Update conversation history (keep last 10 exchanges)
        conversation_history.append({
            'user': query,
            'assistant': result['answer'],
            'timestamp': datetime.utcnow().isoformat()
        })
        
        if len(conversation_history) > 10:
            conversation_history = conversation_history[-10:]
        
        conversations[session_id] = conversation_history
        
        return jsonify({
            'answer': result['answer'],
            'sources': result['sources'],
            'route': result.get('route', 'SEARCH'),
            'timestamp': datetime.utcnow().isoformat()
        })
    
    except Exception as e:
        print(f"Error processing chat: {str(e)}")
        return jsonify({
            'error': 'An error occurred processing your request',
            'details': str(e)
        }), 500

@app.route('/api/clear', methods=['POST'])
def clear_history():
    """Clear conversation history for a session"""
    try:
        data = request.json
        session_id = data.get('session_id', 'default')
        
        if session_id in conversations:
            del conversations[session_id]
        
        return jsonify({
            'message': 'Conversation history cleared',
            'session_id': session_id
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get chatbot statistics"""
    try:
        total_sessions = len(conversations)
        total_messages = sum(len(conv) for conv in conversations.values())
        
        return jsonify({
            'total_sessions': total_sessions,
            'total_messages': total_messages,
            'timestamp': datetime.utcnow().isoformat()
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
