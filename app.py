# app.py
from fastapi import FastAPI, HTTPException, Path, Query, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Dict, Optional, List, Any
from datetime import datetime, timezone
import hashlib
import sqlite3
import json
import re

DB = "strings.db"

def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS strings (
        id TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        properties TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)
    conn.commit()
    conn.close()

init_db()

app = FastAPI(title="String Analyzer Service", version="1.0")

# Pydantic models
class CreateStringRequest(BaseModel):
    value: str = Field(..., description="string to analyze")

class PropertiesModel(BaseModel):
    length: int
    is_palindrome: bool
    unique_characters: int
    word_count: int
    sha256_hash: str
    character_frequency_map: Dict[str, int]

class StoredStringModel(BaseModel):
    id: str
    value: str
    properties: PropertiesModel
    created_at: str

# Utilities
def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def compute_properties(s: str) -> Dict[str, Any]:
    length = len(s)
    is_palindrome = s.lower() == s.lower()[::-1]  # case-insensitive, doesn't strip spaces/punct
    unique_characters = len(set(s))
    word_count = 0
    # define words as sequences separated by whitespace
    words = re.findall(r'\S+', s)
    word_count = len(words)
    h = sha256_hex(s)
    freq = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    return {
        "length": length,
        "is_palindrome": is_palindrome,
        "unique_characters": unique_characters,
        "word_count": word_count,
        "sha256_hash": h,
        "character_frequency_map": freq
    }

def store_string(value: str, properties: Dict[str, Any]):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        cur.execute("INSERT INTO strings (id, value, properties, created_at) VALUES (?, ?, ?, ?)",
                    (properties["sha256_hash"], value, json.dumps(properties), created_at))
        conn.commit()
    finally:
        conn.close()
    return properties["sha256_hash"], created_at

def get_by_hash_or_value(value_or_hash: str):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    # First try id match
    cur.execute("SELECT id, value, properties, created_at FROM strings WHERE id = ? OR value = ?", (value_or_hash, value_or_hash))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    id_, value, properties_json, created_at = row
    properties = json.loads(properties_json)
    return {
        "id": id_,
        "value": value,
        "properties": properties,
        "created_at": created_at
    }

def list_all_stored():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT id, value, properties, created_at FROM strings ORDER BY created_at DESC")
    rows = cur.fetchall()
    conn.close()
    res = []
    for id_, value, properties_json, created_at in rows:
        res.append({
            "id": id_,
            "value": value,
            "properties": json.loads(properties_json),
            "created_at": created_at
        })
    return res

# Natural language query parser (simple heuristics)
def parse_nl_query(q: str) -> Dict[str, Any]:
    q_low = q.lower()
    filters = {}
    # single word / one word
    if re.search(r'\bsingle word\b|\bone word\b', q_low):
        filters["word_count"] = 1
    # palindromic / palindrome
    if re.search(r'palindromic|palindrome', q_low):
        filters["is_palindrome"] = True
    # contains character z / containing the letter z
    m = re.search(r'contain(?:ing)? (?:the )?letter ([a-z])', q_low)
    if not m:
        m = re.search(r'contain(?:ing)? ([a-z])', q_low)
    if m:
        filters["contains_character"] = m.group(1)
    # strings longer than N characters
    m = re.search(r'longer than (\d+) characters|longer than (\d+)', q_low)
    if m:
        num = int(m.group(1) or m.group(2))
        filters["min_length"] = num + 1  # spec example maps "longer than 10" -> min_length=11
    # strings shorter than N
    m = re.search(r'shorter than (\d+) characters|shorter than (\d+)', q_low)
    if m:
        num = int(m.group(1) or m.group(2))
        filters["max_length"] = num - 1 if num>0 else 0
    # example heuristic: "first vowel" => 'a'
    if re.search(r'first vowel', q_low):
        filters["contains_character"] = filters.get("contains_character", "a")
    # direct count e.g. "word_count=2" or "two words"
    m = re.search(r'(\b\d+\b) (?:words|word)', q_low)
    if m:
        filters["word_count"] = int(m.group(1))
    # spelled out numbers (one, two, three)
    numwords = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10}
    for word,num in numwords.items():
        if re.search(r'\b'+word+r' (?:words|word)\b', q_low):
            filters["word_count"] = num
    if not filters:
        raise ValueError("Unable to parse natural language query")
    return filters

# Endpoints
@app.post("/strings", status_code=201, response_model=StoredStringModel)
def create_string(req: CreateStringRequest = Body(...)):
    if not isinstance(req.value, str):
        raise HTTPException(status_code=422, detail="Invalid data type for \"value\" (must be string)")
    value = req.value
    props = compute_properties(value)
    existing = get_by_hash_or_value(props["sha256_hash"])
    if existing:
        # conflict if same hash exists
        raise HTTPException(status_code=409, detail="String already exists in the system")
    id_, created_at = store_string(value, props)
    body = {
        "id": id_,
        "value": value,
        "properties": props,
        "created_at": created_at
    }
    return JSONResponse(status_code=201, content=body)

@app.get("/strings/{string_value}", response_model=StoredStringModel)
def get_string(string_value: str = Path(..., description="URL-encoded string value or sha256 hash")):
    # path parameter will be URL-decoded by FastAPI automatically
    found = get_by_hash_or_value(string_value)
    if not found:
        raise HTTPException(status_code=404, detail="String does not exist in the system")
    return found

@app.get("/strings", response_model=Dict[str, Any])
def get_all_strings(
    is_palindrome: Optional[bool] = Query(None),
    min_length: Optional[int] = Query(None, ge=0),
    max_length: Optional[int] = Query(None, ge=0),
    word_count: Optional[int] = Query(None, ge=0),
    contains_character: Optional[str] = Query(None, min_length=1, max_length=1)
):
    if min_length is not None and max_length is not None and min_length > max_length:
        raise HTTPException(status_code=400, detail="min_length cannot be greater than max_length")
    all_items = list_all_stored()
    filtered = []
    for item in all_items:
        p = item["properties"]
        ok = True
        if is_palindrome is not None and p["is_palindrome"] != is_palindrome:
            ok = False
        if min_length is not None and p["length"] < min_length:
            ok = False
        if max_length is not None and p["length"] > max_length:
            ok = False
        if word_count is not None and p["word_count"] != word_count:
            ok = False
        if contains_character is not None and contains_character not in item["value"]:
            ok = False
        if ok:
            filtered.append(item)
    return {
        "data": filtered,
        "count": len(filtered),
        "filters_applied": {
            k:v for k,v in {
                "is_palindrome": is_palindrome,
                "min_length": min_length,
                "max_length": max_length,
                "word_count": word_count,
                "contains_character": contains_character
            }.items() if v is not None
        }
    }

@app.get("/strings/filter-by-natural-language", response_model=Dict[str, Any])
def natural_filter(query: str = Query(..., description="Natural language query string")):
    try:
        parsed = parse_nl_query(query)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unable to parse natural language query")
    # Apply parsed filters by calling same logic as /strings
    # Map parsed to call
    try:
        result = get_all_strings(
            is_palindrome=parsed.get("is_palindrome"),
            min_length=parsed.get("min_length"),
            max_length=parsed.get("max_length"),
            word_count=parsed.get("word_count"),
            contains_character=parsed.get("contains_character")
        )
    except HTTPException as e:
        raise e
    return {
        "data": result["data"],
        "count": result["count"],
        "interpreted_query": {
            "original": query,
            "parsed_filters": parsed
        }
    }

@app.delete("/strings/{string_value}", status_code=204)
def delete_string(string_value: str = Path(..., description="URL-encoded string value or sha256 hash")):
    found = get_by_hash_or_value(string_value)
    if not found:
        raise HTTPException(status_code=404, detail="String does not exist in the system")
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("DELETE FROM strings WHERE id = ? OR value = ?", (found["id"], found["value"]))
    conn.commit()
    conn.close()
    return JSONResponse(status_code=204, content=None)
