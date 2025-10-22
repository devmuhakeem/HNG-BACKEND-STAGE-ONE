# HNG-BACKEND-STAGE-ONE
# String Analyzer Service — Stage 1

## Overview
RESTful API that analyzes strings and stores computed properties:
- length, is_palindrome (case-insensitive), unique_characters, word_count, sha256_hash, character_frequency_map
Implements endpoints:
- POST /strings
- GET /strings/{string_value}
- GET /strings with filters
- GET /strings/filter-by-natural-language
- DELETE /strings/{string_value}

## Quick start (local)
1. Clone repo
2. Create virtualenv (optional)
   python -m venv .venv
   source .venv/bin/activate  # or .venv\Scripts\activate on Windows
3. Install deps
   pip install -r requirements.txt
4. Run
   uvicorn app:app --reload --host 127.0.0.1 --port 8000

API will be available at: http://127.0.0.1:8000

## Docker
Build:
  docker build -t string-analyzer:latest .
Run:
  docker run -p 8000:8000 string-analyzer:latest

## Persistence
- Uses SQLite file `strings.db` in app directory.

## Endpoints & Examples

### Create / Analyze string
Request:
