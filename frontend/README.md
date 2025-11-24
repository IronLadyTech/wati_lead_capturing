# 🚀 Iron Lady React Dashboard

Modern React frontend for the Iron Lady WATI Analytics system.

## ✨ Features

- 🎨 **Modern UI** - Beautiful gradient-based design
- 💨 **Fast & Smooth** - React for better performance
- 🪟 **Floating Modals** - Query popups without page change
- 📱 **Responsive** - Works on desktop, tablet, mobile
- 🔍 **Search & Filter** - Find leads quickly
- 📊 **Stats Cards** - Visual statistics
- 📥 **CSV Export** - Download leads data
- 📞 **Quick Actions** - One-click call/WhatsApp

## 🎯 Quick Start

### Prerequisites

- Node.js 18+ installed
- Backend running (`python main.py`)

### Installation

```bash
# Navigate to react-dashboard folder
cd react-dashboard

# Install dependencies
npm install

# Start development server
npm run dev
```

Open: http://localhost:3000

### Build for Production

```bash
npm run build
```

## 📁 Project Structure

```
react-dashboard/
├── index.html          # HTML entry
├── package.json        # Dependencies
├── vite.config.js      # Vite configuration
├── public/
│   └── logo.png        # Iron Lady logo
└── src/
    ├── main.jsx        # React entry
    ├── App.jsx         # Main component
    └── App.css         # Styles
```

## 🖥️ Screenshots

### Main Dashboard
- Stats cards showing leads metrics
- Filterable leads table
- Search functionality

### Query Modal (Floating)
- Click 💬 button on any user with Counsellor = Yes
- Modal appears ABOVE the page (floating)
- Shows latest query message
- Quick call/WhatsApp buttons

### User Details Modal
- Click user name to view details
- Full information displayed
- Contact options

## ⚙️ Configuration

### API URL

Edit `src/App.jsx` line 4:
```javascript
const API_URL = 'http://localhost:8000';
```

For production:
```javascript
const API_URL = 'https://your-api-server.com';
```

### Backend CORS

Make sure your `main.py` has CORS enabled:
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or ["http://localhost:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## 🎨 Customization

### Colors

Edit `src/App.css`:

```css
/* Main brand color */
.header {
  background: linear-gradient(135deg, #8B0000 0%, #c41e3a 100%);
}

/* Stats card gradients */
.stat-total .stat-icon { background: linear-gradient(135deg, #667eea, #764ba2); }
.stat-new .stat-icon { background: linear-gradient(135deg, #11998e, #38ef7d); }
```

### Logo

Replace `public/logo.png` with your logo.

## 🔧 Development

### Available Scripts

```bash
npm run dev      # Start dev server
npm run build    # Build for production
npm run preview  # Preview production build
```

### Adding Features

1. Edit `src/App.jsx` for new components
2. Edit `src/App.css` for styles
3. Restart dev server

## 📝 API Endpoints Used

| Endpoint | Description |
|----------|-------------|
| GET /api/users | Fetch all leads |
| GET /api/users/{id} | Fetch user details |
| GET /api/queries | Fetch all queries |

## 🐛 Troubleshooting

### "Failed to fetch data"

1. Check backend is running: `python main.py`
2. Check CORS is enabled in backend
3. Verify API URL in App.jsx

### Styles not loading

1. Clear browser cache
2. Restart dev server: `npm run dev`

### Modal not appearing

1. Check browser console for errors
2. Verify data is loading correctly

## 📱 Mobile Support

The dashboard is fully responsive:
- Desktop: Full table view
- Tablet: Scrollable table
- Mobile: Card-style layout

## 🚀 Deployment

### Using Vercel

```bash
npm run build
vercel deploy
```

### Using Nginx

```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    root /path/to/react-dashboard/dist;
    index index.html;
    
    location / {
        try_files $uri $uri/ /index.html;
    }
    
    location /api {
        proxy_pass http://localhost:8000;
    }
}
```

## 📞 Support

For issues or feature requests, contact the Iron Lady tech team.

---

**Version:** 4.0.0 (React Edition)
**Built with:** React + Vite + FastAPI
