# UAE National Day Video API

A FastAPI service that generates personalized UAE National Day videos with AI-powered image editing and speech-to-video synthesis. Users upload a photo, select their category (Male/Female/Boy/Girl), answer a quiz about UAE National Day, and receive a custom video with a QR code for easy download.

## Features

- **AI Image Editing**: Places user photos in front of Dubai Marina skyline with traditional UAE attire
- **Speech-to-Video**: Generates videos of users singing the UAE national anthem
- **Interactive Quiz**: 10 random questions from a pool of 50 UAE National Day trivia questions
- **QR Code Generation**: Easy video download via QR code
- **Privacy-First**: All media stored locally; no cloud storage required
- **Simple Architecture**: In-memory job management with background threading (no Redis/DB needed)

## Architecture

```
┌─────────────┐      ┌──────────────┐      ┌─────────────────┐
│   Frontend  │─────▶│  FastAPI API │─────▶│ Wavespeed AI    │
│  (React/Vue)│      │  (main.py)   │      │ (qwen + wan2sv) │
└─────────────┘      └──────────────┘      └─────────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │ Local Storage│
                     │ result/      │
                     │ uploads/     │
                     └──────────────┘
```

## API Endpoints

### 1. Create Job
**POST** `/api/jobs`

Start a new video generation job.

**Request:**
- Content-Type: `multipart/form-data`
- Fields:
  - `image`: File (JPEG/PNG only)
  - `age_group`: String (`Male` | `Female` | `Boy` | `Girl`)
  - `phone`: String (optional)

**Response:**
```json
{
  "job_id": "uuid-string"
}
```

**cURL Example:**
```bash
curl -X POST http://localhost:8000/api/jobs \
  -F "image=@photo.jpg" \
  -F "age_group=Male" \
  -F "phone=0501234567"
```

---

### 2. Check Job Status
**GET** `/api/jobs/{job_id}`

Poll job status and retrieve results when ready.

**Responses:**

**While processing:**
```json
{
  "status": "image"  // or "video"
}
```

**Completed:**
```json
{
  "status": "completed",
  "video_url": "https://api.example.com/media/videos/{job_id}.mp4",
  "qr_url": "/api/jobs/{job_id}/qr",
  "error": null
}
```

**Failed:**
```json
{
  "status": "failed",
  "error": "Error message"
}
```

**Poll every 2 seconds from frontend.**

---

### 3. Get QR Code
**GET** `/api/jobs/{job_id}/qr`

Returns a QR code PNG image encoding the video download URL.

**Response:**
- Content-Type: `image/png`
- QR encodes absolute video URL when `PUBLIC_BASE_URL` is set

**Usage:**
```html
<img src="https://api.example.com/api/jobs/{job_id}/qr" alt="Scan to download" />
```

---

### 4. Get Quiz Questions
**GET** `/api/questions?count=10&seed={job_id}`

Fetch random quiz questions for the user.

**Query Parameters:**
- `count`: Number of questions (default: 10)
- `seed`: Optional string to make selection deterministic per job

**Response:**
```json
{
  "questions": [
    {
      "id": 1,
      "question": "When is UAE National Day celebrated?",
      "options": ["2 December", "1 December", "25 November", "15 December"]
    }
    // ...9 more
  ],
  "key": [ /* full questions with answer indices - used for server-side grading */ ]
}
```

**Note:** The `key` array includes correct answers and must be sent back during grading.

---

### 5. Submit Quiz Answers
**POST** `/api/jobs/{job_id}/answers`

Grade the user's quiz answers.

**Request Body:**
```json
{
  "key": [ /* array from /api/questions response */ ],
  "answers": [0, 2, 1, 3, 0, 1, 2, 3, 0, 1]  // user's selected indices
}
```

**Response:**
```json
{
  "total": 10,
  "correct": 7,
  "score": 70
}
```

**Side Effect:** Saves a minimal record to `result/quiz/{job_id}.json`.

---

### 6. Health Check
**GET** `/healthz`

Simple health check endpoint.

**Response:**
```json
{
  "ok": true,
  "time": 1732800000
}
```

---

## Installation & Setup

### Prerequisites
- Python 3.11+
- Docker (optional, for containerized deployment)
- Wavespeed AI API key

### Local Development

1. **Clone the repository:**
```bash
git clone <repo-url>
cd "UAE national anthem"
```

2. **Create virtual environment:**
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

4. **Set environment variables:**
```bash
# Create .env file
cp .env.example .env
# Edit .env and set:
# WSAI_KEY=your_wavespeed_api_key
# PUBLIC_BASE_URL=  (leave empty for local dev)
```

5. **Run the API:**
```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

6. **Test the API:**
```bash
curl http://localhost:8000/healthz
```

---

## Docker Deployment

### Build and Run with Docker Compose

```bash
# Build the image
docker compose build

# Start the service
docker compose up -d

# View logs
docker compose logs -f

# Stop the service
docker compose down
```

The API will be available at `http://localhost:8000`.

---

## AWS Deployment (EC2)

### Step-by-Step Guide

**1. Launch EC2 Instance**
- AMI: Amazon Linux 2023 or Ubuntu 22.04
- Instance Type: t3.small (minimum)
- Storage: 30-100 GB gp3 EBS
- Security Group: Allow 80, 443, 22

**2. Install Docker**
```bash
# Amazon Linux
sudo yum update -y
sudo yum install -y docker git
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker ec2-user

# Install Docker Compose plugin
DOCKER_CONFIG=/usr/local/lib/docker
sudo mkdir -p $DOCKER_CONFIG/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-x86_64 -o $DOCKER_CONFIG/cli-plugins/docker-compose
sudo chmod +x $DOCKER_CONFIG/cli-plugins/docker-compose
```

**3. Deploy Application**
```bash
# Clone repo
cd /srv
sudo git clone <repo-url> uae
cd uae

# Set environment
sudo cp .env.example .env
sudo nano .env  # Set WSAI_KEY and PUBLIC_BASE_URL

# Build and run
sudo docker compose up -d
```

**4. Setup HTTPS with ALB**
- Create Application Load Balancer (internet-facing)
- Target Group: HTTP to EC2 on port 8000
- Health check: `/healthz`, interval 15s
- Listener 443: ACM certificate, forward to target group
- Listener 80: redirect to 443
- Route 53: `api.your-domain.com` → ALB DNS

**5. Update Environment**
```bash
# Update .env with public URL
PUBLIC_BASE_URL=https://api.your-domain.com

# Restart
sudo docker compose up -d
```

---

## Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `WSAI_KEY` | Yes | Wavespeed AI API key | `ws_abc123...` |
| `PUBLIC_BASE_URL` | No* | Public URL of API (for absolute URLs in responses) | `https://api.example.com` |

**Note:** Set `PUBLIC_BASE_URL` in production to ensure video URLs and QR codes use public URLs instead of relative paths.

---

## File Structure

```
UAE national anthem/
├── api/
│   └── main.py           # FastAPI application
├── data/
│   ├── bg.jpg            # Background image
│   ├── questions_uae.json # Quiz question bank (50 questions)
│   ├── male/             # Male assets
│   ├── female/           # Female assets
│   ├── boy/              # Boy assets
│   └── girl/             # Girl assets
├── result/               # Generated outputs (gitignored)
│   ├── videos/           # Generated videos
│   ├── images/           # Edited images
│   └── quiz/             # Quiz results
├── uploads/              # Uploaded images (gitignored)
├── wave.py               # Wavespeed AI integration
├── quiz.py               # Quiz logic
├── data_info.py          # Prompts and paths
├── requirements.txt      # Python dependencies
├── Dockerfile            # Docker image definition
├── docker-compose.yml    # Docker Compose config
├── .env.example          # Environment template
└── README.md             # This file
```

---

## Frontend Integration

### Example React Flow

```tsx
// 1. Start job
const formData = new FormData();
formData.append('image', fileInput.files[0]);
formData.append('age_group', 'Male');
formData.append('phone', '0501234567');

const { job_id } = await fetch('https://api.example.com/api/jobs', {
  method: 'POST',
  body: formData
}).then(r => r.json());

// 2. Load quiz
const { questions, key } = await fetch(
  `https://api.example.com/api/questions?count=10&seed=${job_id}`
).then(r => r.json());

// 3. Poll status every 2s
const interval = setInterval(async () => {
  const status = await fetch(
    `https://api.example.com/api/jobs/${job_id}`
  ).then(r => r.json());
  
  if (status.status === 'completed') {
    setVideoUrl(status.video_url);
    setQrUrl(`https://api.example.com${status.qr_url}`);
    clearInterval(interval);
  }
}, 2000);

// 4. Submit quiz
const result = await fetch(
  `https://api.example.com/api/jobs/${job_id}/answers`,
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, answers: [0,1,2,3,0,1,2,3,0,1] })
  }
).then(r => r.json());

console.log(`Score: ${result.score}%`);

// 5. Display video
<video src={videoUrl} controls />
<img src={qrUrl} alt="QR Code" />
```

---

## Quiz Flow

1. **Page-by-Page Display**: Show one question at a time with radio buttons (single-choice)
2. **Answer Collection**: Store selected indices in an array `[0..9]`
3. **Final Submit**: POST all answers once to `/api/jobs/{id}/answers`
4. **Result Display**: Show score immediately after submission

**Timing:** Quiz can be completed independently of video processing. Video readiness is polled separately.

---

## Video Display Timing

**When does the frontend receive the video?**
- The video URL is returned when `GET /api/jobs/{job_id}` returns `status: "completed"`
- This happens after the pipeline completes: image edit → video generation → local save
- Frontend polls every 2s and updates the UI when the status changes

**Processing Timeline:**
1. `status: "image"` → Image editing in progress (30-60s)
2. `status: "video"` → Video generation in progress (60-120s)
3. `status: "completed"` → Video ready; URLs returned

---

## Privacy & Security

- **No cloud storage**: All media saved locally to `result/` and `uploads/`
- **Minimal data**: Only stores job_id, phone (optional), and quiz score
- **CORS**: Configure `allow_origins` in production to restrict access
- **File validation**: Only JPEG/PNG accepted; recommend max 10MB limit
- **Local-only quiz results**: Scores saved to local JSON files

---

## Performance Notes

- **Workers**: Single worker (`workers=1`) to maintain in-memory job consistency
- **Concurrency**: Background threads handle parallel job processing
- **Polling**: Frontend polls every 2s; minimal load
- **Scaling**: For higher concurrency, switch to file-based job status or add Redis

---

## Troubleshooting

**"Image generation failed"**
- Check WSAI_KEY is valid
- Verify Wavespeed API quota/rate limits
- Check logs for specific error messages

**"Video not appearing"**
- Ensure PUBLIC_BASE_URL is set correctly in production
- Check ALB health checks pass
- Verify /media static files are accessible

**"QR code shows internal path"**
- Set PUBLIC_BASE_URL environment variable
- Restart the service after updating .env

**Upload fails**
- Check file type (only JPEG/PNG)
- Verify file size is reasonable (<10MB recommended)

---

## License

Proprietary - Qmark Services

---

## Support

For issues or questions, contact: support@qmarkservices.com
