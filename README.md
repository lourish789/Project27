# Project27

# Africa Creative Economy Chatbot

A full-stack RAG (Retrieval-Augmented Generation) chatbot application focused on Africa's creative economy, built with Flask backend and Next.js frontend.

## Features

- 🤖 **AI-Powered Chatbot** with RAG using Pinecone and OpenAI
- 📚 **PDF Document Processing** and embedding
- 👤 **User Authentication** (Email/Password + Google OAuth)
- 💬 **Conversation History** - personalized responses based on user history
- 🎨 **Modern UI** with Tailwind CSS
- 🔒 **Secure** JWT-based authentication
- ☁️ **Cloud Ready** - Deploy to Render (backend) and Vercel (frontend)

## Architecture

### Backend (Flask)
- Flask REST API
- PostgreSQL database
- Pinecone vector database
- LangChain for RAG implementation
- JWT authentication
- SQLAlchemy ORM

### Frontend (Next.js)
- Next.js 14 with App Router
- NextAuth.js for authentication
- Tailwind CSS for styling
- Real-time chat interface
- Admin panel for document management

## Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL (or SQLite for development)
- OpenAI API key
- Pinecone API key
- Google OAuth credentials (optional)

## Backend Setup

### 1. Clone and Navigate
```bash
cd backend
```

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Environment Variables
Create a `.env` file:
```bash
SECRET_KEY=your-secret-key-here
DATABASE_URL=postgresql://user:password@localhost:5432/chatbot
# or for development: sqlite:///chatbot.db

OPENAI_API_KEY=your-openai-api-key
PINECONE_API_KEY=your-pinecone-api-key

GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

PORT=5000
```

### 5. Initialize Database
```python
from app import app, db
with app.app_context():
    db.create_all()
```

### 6. Run Backend
```bash
python app.py
# or with gunicorn
gunicorn app:app
```

Backend will run on `http://localhost:5000`

## Frontend Setup

### 1. Navigate to Frontend
```bash
cd frontend
```

### 2. Install Dependencies
```bash
npm install
```

### 3. Environment Variables
Create a `.env.local` file:
```bash
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=your-nextauth-secret-here
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
NEXT_PUBLIC_API_URL=http://localhost:5000
```

### 4. Run Frontend
```bash
npm run dev
```

Frontend will run on `http://localhost:3000`

## Getting API Keys

### OpenAI API Key
1. Go to [OpenAI Platform](https://platform.openai.com/)
2. Create an account or sign in
3. Navigate to API Keys section
4. Create a new secret key

### Pinecone API Key
1. Go to [Pinecone](https://www.pinecone.io/)
2. Sign up for a free account
3. Create a new project
4. Get your API key from the dashboard

### Google OAuth (Optional)
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable Google+ API
4. Create OAuth 2.0 credentials
5. Add authorized redirect URIs:
   - `http://localhost:3000/api/auth/callback/google`
   - Your production URL callback

## Project Structure

```
africa-creative-chatbot/
├── backend/
│   ├── app.py                 # Main Flask application
│   ├── requirements.txt       # Python dependencies
│   ├── .env                   # Environment variables
│   └── render.yaml           # Render deployment config
│
├── frontend/
│   ├── pages/
│   │   ├── _app.js           # Next.js app wrapper
│   │   ├── index.js          # Home page
│   │   ├── chat.js           # Chat interface
│   │   ├── admin.js          # Document management
│   │   └── api/
│   │       └── auth/
│   │           └── [...nextauth].js  # NextAuth config
│   ├── styles/
│   │   └── globals.css       # Global styles
│   ├── package.json          # Node dependencies
│   ├── .env.local            # Environment variables
│   ├── tailwind.config.js    # Tailwind config
│   └── vercel.json           # Vercel deployment config
│
└── README.md
```

## Usage

### 1. Sign Up / Login
- Navigate to `http://localhost:3000`
- Create an account or login with Google
- You'll be redirected to the chat interface

### 2. Add Documents (Admin)
- Navigate to `http://localhost:3000/admin`
- Add PDF URLs of documents about Africa's creative economy
- Documents will be processed and embedded automatically

### 3. Chat
- Ask questions about Africa's creative economy
- The bot uses RAG to retrieve relevant information from uploaded documents
- Responses are personalized based on your conversation history

## Deployment

### Backend (Render)

1. Push your code to GitHub
2. Connect your repo to Render
3. Render will use `render.yaml` for configuration
4. Add environment variables in Render dashboard
5. Deploy!

### Frontend (Vercel)

1. Push your code to GitHub
2. Connect your repo to Vercel
3. Add environment variables in Vercel dashboard:
   - `NEXTAUTH_URL`: Your production URL
   - `NEXTAUTH_SECRET`: Generate with `openssl rand -base64 32`
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `NEXT_PUBLIC_API_URL`: Your Render backend URL
4. Deploy!

## API Endpoints

### Authentication
- `POST /api/auth/signup` - Create new account
- `POST /api/auth/login` - Login with credentials
- `POST /api/auth/google` - Google OAuth login

### Documents
- `POST /api/documents/add` - Add new PDF document (requires auth)
- `GET /api/documents` - List all documents (requires auth)

### Chat
- `POST /api/chat` - Send message to chatbot (requires auth)
- `GET /api/history` - Get conversation history (requires auth)

### Health
- `GET /health` - Check API status

## Security Notes

- Never commit `.env` files
- Use strong SECRET_KEY in production
- Enable CORS only for trusted domains
- Use HTTPS in production
- Rotate API keys regularly
- Implement rate limiting for production

## Customization

### Changing AI Model
In `app.py`, modify the ChatOpenAI initialization:
```python
llm = ChatOpenAI(
    temperature=0.7,
    model_name="gpt-4",  # Change to gpt-3.5-turbo for cost savings
    openai_api_key=os.environ.get('OPENAI_API_KEY')
)
```

### Adjusting RAG Parameters
Modify retrieval settings:
```python
retriever=vectorstore.as_retriever(
    search_kwargs={"k": 3}  # Number of documents to retrieve
)
```

### Customizing UI
- Edit Tailwind classes in frontend components
- Modify color scheme in `tailwind.config.js`
- Update branding and text as needed

## Troubleshooting

### Backend Issues
- **Database connection error**: Check DATABASE_URL format
- **Pinecone error**: Verify API key and index name
- **OpenAI error**: Check API key and rate limits

### Frontend Issues
- **NextAuth error**: Verify NEXTAUTH_SECRET is set
- **API connection error**: Check NEXT_PUBLIC_API_URL
- **Google OAuth error**: Verify redirect URIs

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - feel free to use for your projects!

## Support

For issues or questions, please open an issue on GitHub.

---

Built with ❤️ for Africa's Creative Economy
