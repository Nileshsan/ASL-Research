import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, Response, render_template, request, redirect, url_for, flash, session, send_from_directory, abort
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
PAPERS_DIR = BASE_DIR / 'static' / 'papers'
DATA_DIR.mkdir(exist_ok=True)
PAPERS_DIR.mkdir(parents=True, exist_ok=True)

PUBLICATIONS_FILE = DATA_DIR / 'publications.json'
ADMIN_USER = os.environ.get('ASL_ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('ASL_ADMIN_PASS', 'research123')
SECRET_KEY = os.environ.get('ASL_SECRET_KEY', secrets.token_urlsafe(32))
SITE_URL = os.environ.get('ASL_SITE_URL', 'https://research.appliedsentiencelabs.com').rstrip('/')
SITEMAP_UPDATED = '2026-09-14T00:00:00+00:00'

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['UPLOAD_FOLDER'] = PAPERS_DIR
app.config['MAX_CONTENT_LENGTH'] = 80 * 1024 * 1024


def load_publications():
    if PUBLICATIONS_FILE.exists():
        with PUBLICATIONS_FILE.open('r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_publications(publications):
    with PUBLICATIONS_FILE.open('w', encoding='utf-8') as f:
        json.dump(publications, f, indent=2, ensure_ascii=False)


def get_publication(publication_id):
    return next((pub for pub in load_publications() if pub['id'] == publication_id), None)


def login_required(func):
    def wrapper(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('login', next=request.path))
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


@app.route('/')
def index():
    publications = sorted(load_publications(), key=lambda x: x.get('sort_date', ''), reverse=True)
    return render_template('index.html', publications=publications)


@app.route('/sitemap.xml')
def sitemap():
    urls = [{
        'loc': f'{SITE_URL}/',
        'lastmod': SITEMAP_UPDATED,
        'changefreq': 'weekly',
        'priority': '1.0',
    }]
    urls.extend({
        'loc': f'{SITE_URL}/papers/{pub["pdf_filename"]}',
        'lastmod': datetime.fromtimestamp(
            PUBLICATIONS_FILE.stat().st_mtime,
            tz=timezone.utc,
        ).isoformat(timespec='seconds'),
        'changefreq': 'yearly',
        'priority': '0.4',
    } for pub in load_publications() if pub.get('pdf_filename'))
    sitemap_xml = render_template('sitemap.xml', urls=urls)
    return Response(sitemap_xml, mimetype='application/xml')


@app.route('/robots.txt')
def robots():
    return Response(f'User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /login\nSitemap: {SITE_URL}/sitemap.xml\n', mimetype='text/plain')


@app.route('/papers/<path:filename>')
def paper_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if username == ADMIN_USER and password == ADMIN_PASS:
            session['admin_logged_in'] = True
            flash('Welcome back, admin.', 'success')
            return redirect(url_for('admin'))
        flash('Invalid login credentials.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))


@app.route('/admin')
@login_required
def admin():
    publications = sorted(load_publications(), key=lambda x: x.get('sort_date', ''), reverse=True)
    return render_template('admin.html', publications=publications)


@app.route('/admin/save', methods=['POST'])
@login_required
def save_publication():
    publications = load_publications()
    pub_id = request.form.get('id') or uuid.uuid4().hex
    title = request.form.get('title', '').strip()
    authors = request.form.get('authors', '').strip()
    document_type = request.form.get('document_type', '').strip()
    access = request.form.get('access', '').strip()
    date = request.form.get('date', '').strip()
    abstract = request.form.get('abstract', '').strip()
    tags = [t.strip() for t in request.form.get('tags', '').split(',') if t.strip()]
    external_link = request.form.get('external_link', '').strip()

    if not title or not authors or not date:
        flash('Title, authors, and date are required.', 'error')
        return redirect(url_for('admin'))

    filename = None
    uploaded_file = request.files.get('pdf')
    if uploaded_file and uploaded_file.filename:
        filename = secure_filename(uploaded_file.filename)
        filename = f"{pub_id}-{filename}"
        uploaded_file.save(app.config['UPLOAD_FOLDER'] / filename)

    existing = get_publication(pub_id)
    if existing:
        existing.update({
            'title': title,
            'authors': authors,
            'document_type': document_type,
            'access': access,
            'date': date,
            'abstract': abstract,
            'tags': tags,
            'external_link': external_link,
        })
        if filename:
            existing['pdf_filename'] = filename
    else:
        publication = {
            'id': pub_id,
            'title': title,
            'authors': authors,
            'document_type': document_type,
            'access': access,
            'date': date,
            'abstract': abstract,
            'tags': tags,
            'external_link': external_link,
            'pdf_filename': filename or '',
        }
        publications.append(publication)

    for pub in publications:
        try:
            pub['sort_date'] = datetime.strptime(pub['date'], '%B %Y').strftime('%Y-%m')
        except Exception:
            pub['sort_date'] = pub['date']

    save_publications(publications)
    flash('Publication saved successfully.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/delete/<publication_id>', methods=['POST'])
@login_required
def delete_publication(publication_id):
    publications = load_publications()
    publication = get_publication(publication_id)
    if publication:
        publications = [pub for pub in publications if pub['id'] != publication_id]
        save_publications(publications)
        flash('Publication removed.', 'success')
    else:
        flash('Publication not found.', 'error')
    return redirect(url_for('admin'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
