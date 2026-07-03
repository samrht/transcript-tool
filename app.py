from flask import Flask, request, jsonify, send_file, redirect
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, VideoUnavailable
from concurrent.futures import ThreadPoolExecutor
import re
import json
import zipfile
import io
import threading
from datetime import datetime

app = Flask(__name__, static_folder='public', static_url_path='')
CORS(app)

_video_cache = {}
_cache_lock = threading.Lock()

def extract_video_id(url_or_id):
    patterns = [
        r'(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})',
        r'^([A-Za-z0-9_-]{11})$'
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id.strip())
        if match:
            return match.group(1)
    return None

def get_video_title(video_id):
    try:
        import urllib.request
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read())
            return data.get('title', f'Video_{video_id}')
    except Exception:
        return f'Video_{video_id}'

def fetch_transcript(video_id):
    transcript_list = YouTubeTranscriptApi().list(video_id)
    try:
        transcript = transcript_list.find_manually_created_transcript(['en', 'en-US', 'en-GB'])
    except Exception:
        try:
            transcript = transcript_list.find_generated_transcript(['en', 'en-US', 'en-GB'])
        except Exception:
            transcript = next(iter(transcript_list))

    entries = transcript.fetch().to_raw_data()
    full_text = ' '.join(e['text'] for e in entries)
    full_text = re.sub(r'\s+', ' ', full_text).strip()
    full_text = re.sub(r'\[.*?\]', '', full_text).strip()

    timestamped = []
    for e in entries:
        secs = int(e['start'])
        h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
        ts = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        timestamped.append({'timestamp': ts, 'text': e['text'].strip(), 'start': e['start']})

    word_count = len(full_text.split())
    char_count = len(full_text)
    duration_secs = int(entries[-1]['start'] + entries[-1].get('duration', 0)) if entries else 0
    duration_str = f"{duration_secs // 60}m {duration_secs % 60}s"

    return {
        'full_text': full_text,
        'timestamped': timestamped,
        'word_count': word_count,
        'char_count': char_count,
        'duration': duration_str,
        'language': transcript.language,
        'entry_count': len(entries)
    }

@app.route('/')
def index():
    return redirect('/index.html')

def process_url(url):
    video_id = extract_video_id(url)
    if not video_id:
        return {'url': url, 'video_id': None, 'error': 'Invalid YouTube URL or ID', 'status': 'error'}

    with _cache_lock:
        cached = _video_cache.get(video_id)
    if cached is not None:
        return {'url': url, **cached}

    try:
        title = get_video_title(video_id)
        transcript_data = fetch_transcript(video_id)
        record = {
            'video_id': video_id,
            'title': title,
            'status': 'success',
            'youtube_url': f'https://www.youtube.com/watch?v={video_id}',
            **transcript_data
        }
        with _cache_lock:
            _video_cache[video_id] = record
        return {'url': url, **record}
    except TranscriptsDisabled:
        return {'url': url, 'video_id': video_id, 'error': 'Transcripts are disabled for this video', 'status': 'error'}
    except NoTranscriptFound:
        return {'url': url, 'video_id': video_id, 'error': 'No transcript found', 'status': 'error'}
    except VideoUnavailable:
        return {'url': url, 'video_id': video_id, 'error': 'Video is unavailable or private', 'status': 'error'}
    except Exception as e:
        return {'url': url, 'video_id': video_id, 'error': str(e), 'status': 'error'}

@app.route('/api/fetch', methods=['POST'])
def fetch():
    data = request.get_json(silent=True) or {}
    urls = [u.strip() for u in (data.get('urls') or []) if isinstance(u, str) and u.strip()]

    if not urls:
        return jsonify({'results': []})

    with ThreadPoolExecutor(max_workers=min(8, len(urls))) as pool:
        results = list(pool.map(process_url, urls))

    return jsonify({'results': results})

@app.route('/api/export', methods=['POST'])
def export():
    data = request.get_json(silent=True) or {}
    results = data.get('results', [])
    fmt = data.get('format', 'txt')
    export_type = data.get('export_type', 'zip')

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    def safe_name(title, video_id):
        name = re.sub(r'[^\w\s-]', '', title)[:60].strip()
        return f"{name}_{video_id}" if name else video_id

    def to_json_record(r):
        return {
            'video_id': r['video_id'],
            'title': r['title'],
            'youtube_url': r.get('youtube_url'),
            'language': r.get('language'),
            'word_count': r.get('word_count'),
            'duration': r.get('duration'),
            'transcript': r['full_text'],
            'timestamped': r.get('timestamped', [])
        }

    def txt_header_lines(r):
        return [
            f"Title: {r['title']}",
            f"Video ID: {r['video_id']}",
            f"URL: {r.get('youtube_url','')}",
            f"Language: {r.get('language','')}",
            f"Words: {r.get('word_count','')}",
            f"Duration: {r.get('duration','')}",
        ]

    def markdown_doc(r):
        return '\n'.join([
            f"# {r['title']}", '',
            f"- **Video ID:** {r['video_id']}",
            f"- **URL:** {r.get('youtube_url','')}",
            f"- **Language:** {r.get('language','')}",
            f"- **Words:** {r.get('word_count','')}",
            f"- **Duration:** {r.get('duration','')}", '',
            r['full_text']
        ])

    success_results = [r for r in results if r.get('status') == 'success']

    if export_type == 'single_json':
        content = json.dumps([to_json_record(r) for r in success_results], indent=2, ensure_ascii=False)
        buf = io.BytesIO(content.encode('utf-8'))
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=f'transcripts_{timestamp}.json', mimetype='application/json')

    if export_type == 'single_txt':
        lines = []
        for r in success_results:
            lines.append('=' * 60)
            lines.extend(txt_header_lines(r))
            lines.append('=' * 60)
            lines.append(r['full_text'])
            lines.append('')
        content = '\n'.join(lines)
        buf = io.BytesIO(content.encode('utf-8'))
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=f'transcripts_{timestamp}.txt', mimetype='text/plain')

    if export_type == 'single_markdown':
        lines = []
        for r in success_results:
            lines.append(markdown_doc(r))
            lines.append('')
            lines.append('---')
            lines.append('')
        content = '\n'.join(lines)
        buf = io.BytesIO(content.encode('utf-8'))
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=f'transcripts_{timestamp}.md', mimetype='text/markdown')

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for r in success_results:
            fname = safe_name(r['title'], r['video_id'])
            if fmt == 'json':
                content = json.dumps(to_json_record(r), indent=2, ensure_ascii=False)
                zf.writestr(f"{fname}.json", content)
            elif fmt == 'timestamped':
                lines = [f"Title: {r['title']}", f"URL: {r.get('youtube_url','')}", f"Duration: {r.get('duration','')}", ""]
                for entry in r.get('timestamped', []):
                    lines.append(f"[{entry['timestamp']}] {entry['text']}")
                zf.writestr(f"{fname}_timestamped.txt", '\n'.join(lines))
            elif fmt == 'markdown':
                zf.writestr(f"{fname}.md", markdown_doc(r) + '\n')
            else:
                header = '\n'.join(txt_header_lines(r)) + '\n\n'
                zf.writestr(f"{fname}.txt", header + r['full_text'])

    zip_buf.seek(0)
    return send_file(zip_buf, as_attachment=True, download_name=f'transcripts_{timestamp}.zip', mimetype='application/zip')

if __name__ == '__main__':
    print("\n  YouTube Transcript Extractor")
    print("  Open http://localhost:5050 in your browser\n")
    app.run(debug=False, port=5050)
