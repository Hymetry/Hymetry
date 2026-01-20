const express = require('express');
const path = require('path');
const fs = require('fs').promises;

const app = express();
const PORT = 3001;

// Middleware
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// In-memory storage for demo purposes
// In real app, this would come from database
let eventsData = null;

// Load events data on startup
async function loadEventsData() {
  try {
    const eventsText = await fs.readFile(path.join(__dirname, 'public', 'events2.txt'), 'utf8');
    // Decode HTML-escaped quotes
    const decoded = eventsText.replace(/&quot;/g, '"');
    eventsData = JSON.parse(decoded);
    console.log(`Loaded ${eventsData.length} events`);
  } catch (error) {
    console.error('Error loading events data:', error);
    eventsData = [];
  }
}

// API endpoint for paginated session events
app.get('/api/sessions/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const { offset = 0, limit = 20 } = req.query;  // Reduced default limit to 20
    
    const offsetNum = parseInt(offset);
    const limitNum = parseInt(limit);
    
    if (!eventsData) {
      return res.status(500).json({ 
        error: 'Events data not loaded' 
      });
    }
    
    // Get paginated events
    const startIndex = offsetNum;
    const endIndex = Math.min(startIndex + limitNum, eventsData.length);
    const events = eventsData.slice(startIndex, endIndex);
    
    // Check if there are more events
    const hasMore = endIndex < eventsData.length;
    
    // Calculate total count
    const totalCount = eventsData.length;
    
    // Add some delay to simulate network latency
    await new Promise(resolve => setTimeout(resolve, 100));
    
    res.json({
      events,
      pagination: {
        offset: offsetNum,
        limit: limitNum,
        hasMore,
        totalCount,
        currentCount: events.length
      }
    });
    
  } catch (error) {
    console.error('Error serving session events:', error);
    res.status(500).json({ 
      error: 'Internal server error' 
    });
  }
});

// Health check endpoint
app.get('/api/health', (req, res) => {
  res.json({ 
    status: 'ok', 
    eventsLoaded: eventsData ? eventsData.length : 0 
  });
});

// Start server
async function startServer() {
  await loadEventsData();
  
  app.listen(PORT, () => {
    console.log(`Server running on http://localhost:${PORT}`);
    console.log(`API endpoint: http://localhost:${PORT}/api/sessions/:id?offset=0&limit=100`);
    console.log(`Player page: http://localhost:${PORT}/player_stream.html`);
  });
}

startServer().catch(console.error); 