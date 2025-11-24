# 🚀 Quick Setup - React Dashboard

## Step 1: Install Node.js

Download and install from: https://nodejs.org/ (LTS version)

Verify:
```bash
node --version   # Should show v18+
npm --version    # Should show 9+
```

## Step 2: Start Backend

```bash
cd C:\Projects\wati-analytics
python main.py
```

Keep this running!

## Step 3: Setup React Frontend

```bash
# Open NEW terminal
cd C:\Projects\wati-analytics\react-dashboard

# Install dependencies (first time only)
npm install

# Start development server
npm run dev
```

## Step 4: Open Dashboard

Browser: http://localhost:3000

## 🎉 Done!

You should see the modern React dashboard with:
- ✅ Stats cards
- ✅ Leads table
- ✅ Floating query modal (click 💬)
- ✅ User detail modal (click name)
- ✅ Filters and search
- ✅ CSV export

---

## 🔧 Troubleshooting

### "npm not found"
→ Install Node.js from nodejs.org

### "Failed to fetch data"
→ Make sure backend is running: `python main.py`

### Port 3000 in use
Edit `vite.config.js`:
```javascript
server: {
  port: 3001  // Change to another port
}
```

---

## 📁 File Structure

```
C:\Projects\wati-analytics\
├── main.py              # Backend (run this first)
├── dashboard.py         # Old Streamlit (optional)
└── react-dashboard\     # New React frontend
    ├── package.json
    ├── src\
    │   ├── App.jsx      # Main component
    │   └── App.css      # Styles
    └── public\
        └── logo.png
```

---

## 🚀 Running Both

Terminal 1 (Backend):
```bash
cd C:\Projects\wati-analytics
python main.py
```

Terminal 2 (React):
```bash
cd C:\Projects\wati-analytics\react-dashboard
npm run dev
```

Open: http://localhost:3000
