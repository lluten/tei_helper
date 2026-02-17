import os
import json
import uuid
import re
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from flask import Flask, render_template, request, Response, redirect, url_for, session, send_from_directory
from markupsafe import Markup, escape
from flask_session import Session
from lxml import etree
from bs4 import BeautifulSoup

app = Flask(__name__)

# --- CONFIGURATION (env for web deployment) ---
app.secret_key = os.environ.get('SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY') or 'tei_secret_key_dev_only'
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads'))
TAGS_FILE = os.environ.get('TAGS_FILE', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tags.json'))
TEI_LAYOUT_FILE = os.environ.get('TEI_LAYOUT_FILE', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tei_layout_template.xml'))
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Server-side sessions (avoid cookie size limit for doc_meta / imported_lines)
app.config['SESSION_TYPE'] = os.environ.get('SESSION_TYPE', 'filesystem')
app.config['SESSION_FILE_DIR'] = os.environ.get('SESSION_FILE_DIR') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'flask_session'
)
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
Session(app)

DEFAULT_TAGS = []

def load_tags():
    if not os.path.exists(TAGS_FILE): return DEFAULT_TAGS
    try:
        with open(TAGS_FILE, 'r') as f:
            tags = json.load(f)
            order = {'visual': 1, 'editorial': 2, 'semantic': 3, 'structural': 4}
            tags.sort(key=lambda x: (order.get(x.get('category'), 99), x.get('label')))
            return tags
    except: return DEFAULT_TAGS

def save_tags(tags):
    with open(TAGS_FILE, 'w') as f:
        json.dump(tags, f, indent=2)

# Updated Skeleton based on user requirements (indented for layout editor readability)
TEI_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<?xml-model href="https://vault.tei-c.org/P5/current/xml/tei/custom/schema/relaxng/tei_all.rng" schematypens="http://relaxng.org/ns/structure/1.0" type="application/xml"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title>{title}</title>
        <author>{author}
        <date>{date}</date>
        </author>
        <respStmt>
          <resp>transcribed by</resp>
          <name>{transcriber}</name>
        </respStmt>
        <respStmt>
          <resp>validated by</resp>
          <name>TEI-edit</name>
        </respStmt>
      </titleStmt>
      <publicationStmt>
        <p>Transcribed using TEI-edit.</p>
      </publicationStmt>
      <sourceDesc>
        <msDesc>
          <msIdentifier>
            <country>{country}</country>
            <settlement>{settlement}</settlement>
            <repository>{repository}</repository>
            <idno>{idno}</idno>
          </msIdentifier>
          <physDesc>
            <objectDesc>
              <supportDesc>
                <support>
                  <material>{material}</material>
                  <objectType>{objectType}</objectType>
                  <dimensions></dimensions>
                </support>
              </supportDesc>
              <layoutDesc>
                <layout></layout>
              </layoutDesc>
            </objectDesc>
            <handDesc>
              <handNote>{handNote}</handNote>
            </handDesc>
          </physDesc>
          <history>
            <origin></origin>
            <provenance></provenance>
          </history>
        </msDesc>
      </sourceDesc>
    </fileDesc>
    <encodingDesc>
      <projectDesc><p>Digital Transcription.</p></projectDesc>
      <editorialDecl>
        <p>Capital and lowercase letters will be normalized.</p>
      </editorialDecl>
    </encodingDesc>
    <profileDesc>
      <langUsage><p>{language}</p></langUsage>
    </profileDesc>
  </teiHeader>
  <text>
    <body>
      <div type="edition"></div>
    </body>
  </text>
</TEI>
"""

def get_tei_template():
    """Load TEI header/body template: custom file if present, else built-in. Placeholders: title, author, date, transcriber, country, settlement, repository, idno, material, objectType, handNote, language."""
    if os.path.isfile(TEI_LAYOUT_FILE):
        try:
            with open(TEI_LAYOUT_FILE, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            pass
    return TEI_TEMPLATE

def _indent_xml_string(xml_str, indent_str='  '):
    """Indent XML by tracking tag depth. Does not require valid XML (no parse)."""
    xml_str = xml_str.strip()
    if not xml_str:
        return xml_str
    out = []
    depth = 0
    i = 0
    n = len(xml_str)
    while i < n:
        # Skip whitespace between tags
        if xml_str[i] in ' \t\n\r':
            i += 1
            continue
        if xml_str[i] != '<':
            # Text content: take until next <
            start = i
            while i < n and xml_str[i] != '<':
                i += 1
            text = xml_str[start:i].strip()
            if text:
                out.append(depth * indent_str + text)
            continue
        # We're at '<'
        start = i
        if i + 1 < n and xml_str[i + 1] == '?':
            # PI: <?...?>
            end = xml_str.find('?>', i) + 2
            if end <= i:
                end = n
            out.append(xml_str[start:end])
            i = end
            continue
        if i + 1 < n and xml_str[i + 1] == '!':
            # Comment: <!-- ... -->
            end = xml_str.find('-->', i) + 3
            if end <= i:
                end = n
            out.append(depth * indent_str + xml_str[start:end])
            i = end
            continue
        # Find end of tag
        j = i + 1
        while j < n and xml_str[j] != '>':
            if xml_str[j] in '"\'':
                q = xml_str[j]
                j += 1
                while j < n and xml_str[j] != q:
                    j += 1
                if j < n:
                    j += 1
            else:
                j += 1
        if j >= n:
            j = n
        tag = xml_str[start:j + 1]
        i = j + 1
        is_closing = tag.startswith('</')
        is_self_closing = tag.rstrip().endswith('/>')
        if is_closing or is_self_closing:
            depth = max(0, depth - 1)
        out.append(depth * indent_str + tag)
        if not is_closing and not is_self_closing:
            depth += 1
    return '\n'.join(out)

def _safe_layout_display(xml_str):
    """Escape only the sequence that would break the textarea, then mark safe for HTML so XML displays with indents."""
    if not xml_str:
        return Markup('')
    safe = xml_str.replace('</textarea>', '</tei' + 'xtarea>')
    return Markup(safe)

# --- PAGE HELPERS (multi-page session model) ---

def build_page_from_pagexml(filepath):
    """Build a page dict from a Transkribus PageXML file."""
    tree = etree.parse(filepath)
    img_url = ""
    raw_img_url = ""
    meta = tree.xpath('//*[local-name()="TranskribusMetadata"]')
    if meta:
        raw_img_url = meta[0].get('imgUrl') or ""
        if raw_img_url and (raw_img_url.startswith('http://') or raw_img_url.startswith('https://')):
            img_url = url_for('proxy_image', url=raw_img_url, _external=False)
        else:
            img_url = raw_img_url or ""
    orig_w, orig_h = 0, 0
    page_el = tree.xpath('//*[local-name()="Page"]')
    if page_el:
        orig_w = int(page_el[0].get('imageWidth', 0))
        orig_h = int(page_el[0].get('imageHeight', 0))
    lines_data = []
    for i, node in enumerate(tree.xpath('//*[local-name()="TextLine"]')):
        t_node = node.xpath('.//*[local-name()="Unicode"]/text()')
        text = t_node[0] if t_node else ""
        c_node = node.xpath('.//*[local-name()="Coords"]')
        points = c_node[0].get('points') if c_node else ""
        lines_data.append({'id': i, 'text': text, 'points': points, 'html': ''})
    return {
        'file': filepath,
        'lines': lines_data,
        'html': None,
        'img_url': img_url,
        'orig_width': orig_w,
        'orig_height': orig_h,
        'image_src': raw_img_url,
        'import_type': 'transkribus',
    }


def build_page_from_tei(tree, filepath):
    """Build a page dict from a TEI tree (body lines only). Caller sets session['doc_meta']."""
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    body = tree.xpath('//t:body/t:div', namespaces=ns)
    if not body:
        body = tree.xpath('//t:body', namespaces=ns)
    lines_data = []
    if body:
        body_xml = etree.tostring(body[0], encoding='unicode')
        body_xml = re.sub(r'^<[^>]+>', '', body_xml)
        body_xml = re.sub(r'</[^>]+>$', '', body_xml)
        raw_lines = re.split(r'<lb[^>]*>', body_xml)

        def tag_replacer(match):
            tag = match.group(1)
            attrs = match.group(2)
            content = match.group(3)
            attr_str = ""
            for k, v in re.findall(r'(\w+)="([^"]*)"', attrs):
                attr_str += f' data-attr-{k}="{v}"'
            return f'<span class="tei-tag tag-{tag}" data-tag="{tag}"{attr_str}>{content}</span>'

        for i, line_content in enumerate(raw_lines):
            if not line_content.strip():
                continue
            html_line = re.sub(r'<(\w+)([^>]*)>(.*?)</\1>', tag_replacer, line_content)
            html_line = html_line.replace('xmlns="http://www.tei-c.org/ns/1.0"', '')
            text_only = re.sub(r'<[^>]+>', '', line_content).strip()
            lines_data.append({
                'id': i,
                'text': text_only,
                'html': html_line.strip(),
                'points': '',
            })
    return {
        'file': filepath,
        'lines': lines_data,
        'html': None,
        'img_url': '',
        'orig_width': 0,
        'orig_height': 0,
        'image_src': '',
        'import_type': 'tei',
    }


def build_page_from_image(filepath):
    """Build a page dict from an image file (one empty line, no coords)."""
    orig_w, orig_h = 0, 0
    try:
        from PIL import Image
        with Image.open(filepath) as im:
            orig_w, orig_h = im.size[0], im.size[1]
    except Exception:
        pass
    filename = os.path.basename(filepath)
    img_url = url_for('send_upload', filename=filename)
    return {
        'file': filepath,
        'lines': [{'id': 0, 'text': '', 'html': '', 'points': ''}],
        'html': None,
        'img_url': img_url,
        'orig_width': orig_w,
        'orig_height': orig_h,
        'image_src': '',
        'import_type': 'image',
    }


@app.route('/uploads/<path:filename>')
def send_upload(filename):
    """Serve uploaded files (e.g. images for image-only import)."""
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        import_type = request.form.get('import_type', 'transkribus')
        uploaded_files = request.files.getlist('file')
        if not uploaded_files or not uploaded_files[0].filename:
            return render_template('index.html', error='Please select at least one file.')
        pages = []
        session['doc_meta'] = session.get('doc_meta') or {}
        for uploaded_file in uploaded_files:
            if not uploaded_file.filename:
                continue
            filename = f"{uuid.uuid4()}_{uploaded_file.filename}"
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            uploaded_file.save(filepath)
            if import_type == 'image':
                page = build_page_from_image(filepath)
            elif import_type == 'tei':
                try:
                    tree = etree.parse(filepath)
                    root = tree.getroot()
                    if 'TEI' in root.tag or 'ns/1.0' in root.tag:
                        meta = {}
                        ns = {'t': 'http://www.tei-c.org/ns/1.0'}
                        def get_text(xpath):
                            res = tree.xpath(xpath, namespaces=ns)
                            return res[0].text if res and res[0].text else ""
                        meta['title'] = get_text('//t:titleStmt/t:title')
                        meta['author'] = get_text('//t:titleStmt/t:author')
                        meta['date'] = get_text('//t:titleStmt/t:author/t:date')
                        meta['transcriber'] = get_text('//t:respStmt/t:name')
                        meta['country'] = get_text('//t:msIdentifier/t:country')
                        meta['settlement'] = get_text('//t:msIdentifier/t:settlement')
                        meta['repository'] = get_text('//t:msIdentifier/t:repository')
                        meta['idno'] = get_text('//t:msIdentifier/t:idno')
                        meta['material'] = get_text('//t:support/t:material')
                        meta['objectType'] = get_text('//t:support/t:objectType')
                        meta['handNote'] = get_text('//t:handDesc/t:handNote')
                        meta['language'] = get_text('//t:langUsage/t:p')
                        session['doc_meta'] = meta
                        page = build_page_from_tei(tree, filepath)
                    else:
                        page = build_page_from_pagexml(filepath)
                except Exception as e:
                    return f"Error parsing {uploaded_file.filename}: {e}", 400
            else:
                try:
                    tree = etree.parse(filepath)
                    root = tree.getroot()
                    if 'TEI' in root.tag or 'ns/1.0' in root.tag:
                        session['doc_meta'] = {}
                        page = build_page_from_tei(tree, filepath)
                    else:
                        session['doc_meta'] = session.get('doc_meta') or {}
                        page = build_page_from_pagexml(filepath)
                except Exception as e:
                    return f"Error parsing {uploaded_file.filename}: {e}", 400
            pages.append(page)
        if not pages:
            return render_template('index.html', error='No valid files.')
        session['pages'] = pages
        session['current_page_index'] = 0
        return redirect(url_for('editor'))

    if session.get('pages') and len(session['pages']) > 0:
        return redirect(url_for('editor'))

    return render_template('index.html')

def parse_tei_import(tree):
    """Extracts metadata and content from an existing TEI file to allow re-editing."""
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    
    # 1. Extract Metadata for Header
    meta = {}
    def get_text(xpath):
        res = tree.xpath(xpath, namespaces=ns)
        return res[0].text if res and res[0].text else ""
    
    meta['title'] = get_text('//t:titleStmt/t:title')
    meta['author'] = get_text('//t:titleStmt/t:author') # Careful: author might contain date node
    meta['date'] = get_text('//t:titleStmt/t:author/t:date')
    meta['transcriber'] = get_text('//t:respStmt/t:name')
    meta['country'] = get_text('//t:msIdentifier/t:country')
    meta['settlement'] = get_text('//t:msIdentifier/t:settlement')
    meta['repository'] = get_text('//t:msIdentifier/t:repository')
    meta['idno'] = get_text('//t:msIdentifier/t:idno')
    meta['material'] = get_text('//t:support/t:material')
    meta['objectType'] = get_text('//t:support/t:objectType')
    meta['handNote'] = get_text('//t:handDesc/t:handNote')
    meta['language'] = get_text('//t:langUsage/t:p')
    
    session['doc_meta'] = meta

    # 2. Extract Body Content (Lines)
    # We look for <lb> tags and split content.
    # Note: To preserve tags like <persName>, we need to handle XML-to-HTML conversion.
    
    # Strategy: Dump the body to string, split by <lb>, then parse fragments to HTML spans
    body = tree.xpath('//t:body/t:div', namespaces=ns)
    if not body: body = tree.xpath('//t:body', namespaces=ns)
    
    lines_data = []
    
    if body:
        # Get full XML string of body content
        body_xml = etree.tostring(body[0], encoding='unicode')
        
        # Remove the outer div/body tag to get inner content
        body_xml = re.sub(r'^<[^>]+>', '', body_xml)
        body_xml = re.sub(r'</[^>]+>$', '', body_xml)
        
        # Split by <lb ... />
        # We try to preserve 'points' if we saved them previously
        raw_lines = re.split(r'<lb[^>]*>', body_xml)
        
        # Find points attributes in the split delimiters (complex via regex split, simplified here)
        # For this version, we accept that re-imported TEI might lose precise Image Alignment
        # unless we parse it strictly node-by-node. 
        # To keep "Edit Existing" working for text + tags:
        
        for i, line_content in enumerate(raw_lines):
            if not line_content.strip(): continue
            
            # Convert TEI tags back to Editor HTML Spans
            # e.g. <persName ref="x">Name</persName> -> <span class="tei-tag tag-persName" data-tag="persName" data-attr-ref="x">Name</span>
            
            # Simple Regex replacement for common tags (robust approach would be XSLT)
            # We replace <tag attrs>content</tag> with <span ...>content</span>
            
            def tag_replacer(match):
                tag = match.group(1)
                attrs = match.group(2)
                content = match.group(3)
                
                # Parse attributes
                attr_str = ""
                key_vals = re.findall(r'(\w+)="([^"]*)"', attrs)
                for k, v in key_vals:
                    attr_str += f' data-attr-{k}="{v}"'
                
                return f'<span class="tei-tag tag-{tag}" data-tag="{tag}"{attr_str}>{content}</span>'

            # Regex for simple nested tags
            html_line = re.sub(r'<(\w+)([^>]*)>(.*?)</\1>', tag_replacer, line_content)
            
            # Strip remaining namespaces or unwanted formatting
            html_line = html_line.replace('xmlns="http://www.tei-c.org/ns/1.0"', '')
            
            text_only = re.sub(r'<[^>]+>', '', line_content).strip()
            
            lines_data.append({
                'id': i,
                'text': text_only,
                'html': html_line.strip(), # Pass HTML to editor
                'points': "" # Lost on TEI import currently
            })
            
        session['imported_lines'] = lines_data

    return redirect(url_for('editor'))

@app.route('/doc_info', methods=['GET'])
def doc_info():
    meta = session.get('doc_meta', {})
    return render_template('doc_info.html', meta=meta)

@app.route('/save_doc_info', methods=['POST'])
def save_doc_info():
    session['doc_meta'] = request.form.to_dict()
    return redirect(url_for('editor'))

@app.route('/editor')
def editor():
    pages = session.get('pages')
    if not pages:
        return redirect(url_for('index'))
    current_index = session.get('current_page_index', 0)
    if current_index < 0 or current_index >= len(pages):
        current_index = 0
        session['current_page_index'] = 0
    page = pages[current_index]
    file_path = page.get('file')
    if not file_path or not os.path.exists(file_path):
        return redirect(url_for('index'))

    lines_in = page.get('lines', [])
    stored_html = page.get('html')
    if stored_html:
        initial_html = stored_html
    else:
        initial_html = None

    tags = load_tags()
    page_name = os.path.basename(file_path) if file_path else ""
    highlight_gram = request.args.get('highlight')
    page_labels = [os.path.basename(p.get('file', '')) or ('Page ' + str(i + 1)) for i, p in enumerate(pages)]
    pages_summary = [{'label': page_labels[i], 'line_count': len(p.get('lines', []))} for i, p in enumerate(pages)]
    return render_template('editor.html',
                           lines=lines_in,
                           img_url=page.get('img_url', ''),
                           orig_width=page.get('orig_width', 0),
                           orig_height=page.get('orig_height', 0),
                           tags=tags,
                           page_name=page_name,
                           line_count=len(lines_in),
                           image_src=page.get('image_src', ''),
                           initial_html=initial_html,
                           current_page_index=current_index,
                           total_pages=len(pages),
                           highlight_gram=highlight_gram,
                           import_type=page.get('import_type', 'transkribus'),
                           page_labels=page_labels,
                           pages_summary=pages_summary)

@app.route('/editor/switch_page', methods=['POST'])
def switch_page():
    pages = session.get('pages')
    if not pages:
        return redirect(url_for('index'))
    current_index = session.get('current_page_index', 0)
    target_index = request.form.get('target_page_index', type=int)
    if target_index is not None and 0 <= target_index < len(pages):
        html_content = request.form.get('html_content', '')
        if current_index < len(pages):
            session['pages'][current_index]['html'] = html_content
        session['current_page_index'] = target_index
    highlight_gram = request.form.get('highlight_gram') or request.args.get('highlight')
    keep_ligatures = request.form.get('keep_ligatures')
    url = url_for('editor')
    if highlight_gram:
        url = url_for('editor', highlight=highlight_gram)
    if keep_ligatures:
        url = url + ('&' if '?' in url else '?') + 'ligatures=1'
    return redirect(url)


@app.route('/editor/change_image', methods=['POST'])
def change_image():
    """Replace the image for the current page with an uploaded image file."""
    pages = session.get('pages')
    if not pages:
        return redirect(url_for('index'))
    current_index = session.get('current_page_index', 0)
    if current_index < 0 or current_index >= len(pages):
        return redirect(url_for('editor'))
    f = request.files.get('image')
    if not f or not f.filename:
        return redirect(url_for('editor'))
    ext = os.path.splitext(f.filename)[-1].lower() or '.png'
    if ext not in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff', '.tif'):
        return redirect(url_for('editor'))
    filename = f"{uuid.uuid4()}_{f.filename}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    f.save(filepath)
    orig_w, orig_h = 0, 0
    try:
        from PIL import Image
        with Image.open(filepath) as im:
            orig_w, orig_h = im.size[0], im.size[1]
    except Exception:
        pass
    img_url = url_for('send_upload', filename=filename)
    page = session['pages'][current_index]
    page['img_url'] = img_url
    page['orig_width'] = orig_w
    page['orig_height'] = orig_h
    page['image_src'] = ''
    if page.get('import_type') == 'image':
        page['file'] = filepath
    return redirect(url_for('editor'))


@app.route('/editor/reorder_pages', methods=['POST'])
def reorder_pages():
    """Apply new page order; order is comma-separated indices e.g. 0,2,1,3."""
    pages = session.get('pages')
    if not pages or len(pages) < 2:
        return redirect(url_for('editor'))
    order_str = request.form.get('order')
    if not order_str:
        return redirect(url_for('editor'))
    try:
        new_order = [int(x.strip()) for x in order_str.split(',') if x.strip()]
    except ValueError:
        return redirect(url_for('editor'))
    if set(new_order) != set(range(len(pages))) or len(new_order) != len(pages):
        return redirect(url_for('editor'))
    reordered = [pages[i] for i in new_order]
    current_index = session.get('current_page_index', 0)
    old_page = pages[current_index]
    new_index = reordered.index(old_page)
    session['pages'] = reordered
    session['current_page_index'] = new_index
    return redirect(url_for('editor'))


@app.route('/editor/add_pages', methods=['POST'])
def add_pages():
    """Append new page(s) from uploaded file(s). Saves current page HTML first."""
    pages = session.get('pages')
    if not pages:
        return redirect(url_for('index'))
    current_index = session.get('current_page_index', 0)
    html_content = request.form.get('html_content', '')
    if current_index < len(pages):
        session['pages'][current_index]['html'] = html_content
    uploaded = request.files.getlist('file')
    for f in uploaded:
        if not f or not f.filename:
            continue
        filename = f"{uuid.uuid4()}_{f.filename}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        f.save(filepath)
        ext = os.path.splitext(f.filename)[-1].lower()
        if ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff', '.tif'):
            new_page = build_page_from_image(filepath)
        else:
            try:
                tree = etree.parse(filepath)
                root = tree.getroot()
                if 'TEI' in root.tag or 'ns/1.0' in root.tag:
                    new_page = build_page_from_tei(tree, filepath)
                else:
                    new_page = build_page_from_pagexml(filepath)
            except Exception:
                continue
        session['pages'].append(new_page)
    return redirect(url_for('editor'))


@app.route('/editor/remove_pages', methods=['POST'])
def remove_pages():
    """Remove pages at given indices (comma-separated). Saves current page HTML first."""
    pages = session.get('pages')
    if not pages:
        return redirect(url_for('editor'))
    current_index = session.get('current_page_index', 0)
    html_content = request.form.get('html_content', '')
    if current_index < len(pages):
        session['pages'][current_index]['html'] = html_content
    indices_str = request.form.get('indices', '')
    try:
        to_remove = sorted(set(int(x.strip()) for x in indices_str.split(',') if x.strip()), reverse=True)
    except ValueError:
        return redirect(url_for('editor'))
    if not to_remove:
        return redirect(url_for('editor'))
    for i in to_remove:
        if 0 <= i < len(session['pages']):
            session['pages'].pop(i)
            if current_index == i:
                current_index = max(0, min(current_index, len(session['pages']) - 1))
            elif current_index > i:
                current_index -= 1
    session['current_page_index'] = current_index
    if not session['pages']:
        return redirect(url_for('index'))
    return redirect(url_for('editor'))


def _page_line_texts(page):
    """Return list of plain-text strings, one per line, for a page (from stored html or lines)."""
    html = page.get('html')
    if html:
        soup = BeautifulSoup(html, 'html.parser')
        return [div.get_text(strip=True) for div in soup.find_all(class_='line-wrapper')]
    lines = page.get('lines', [])
    return [line.get('text', '') for line in lines]


@app.route('/api/ligature_lines', methods=['GET', 'POST'])
def api_ligature_lines():
    """Return line texts for all pages (for ligature analysis across pages). POST may include html_content and current_page_index to save current page first."""
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        html_content = data.get('html_content')
        try:
            current_index = int(data.get('current_page_index', session.get('current_page_index', 0)))
        except (TypeError, ValueError):
            current_index = session.get('current_page_index', 0)
        pages = session.get('pages', [])
        if html_content is not None and 0 <= current_index < len(pages):
            session['pages'][current_index]['html'] = html_content
    pages = session.get('pages', [])
    lines_by_page = [_page_line_texts(p) for p in pages]
    return Response(json.dumps({'linesByPage': lines_by_page}), mimetype='application/json')


@app.route('/proxy_image')
def proxy_image():
    """Proxy external image URLs (e.g. Transkribus) to avoid CORS when loading in the editor."""
    url = request.args.get('url')
    if not url:
        return Response('Missing url parameter', status=400)
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return Response('Invalid URL scheme', status=400)
    try:
        req = Request(url, headers={'User-Agent': 'TEI-Helper/1.0'})
        with urlopen(req, timeout=30) as resp:
            data = resp.read()
            content_type = resp.headers.get('Content-Type', 'image/jpeg')
    except Exception as e:
        return Response(f'Proxy error: {e}', status=502)
    return Response(data, mimetype=content_type)

@app.route('/close')
def close_file():
    session.pop('current_file', None)
    session.pop('doc_meta', None)
    session.pop('imported_lines', None)
    session.pop('pages', None)
    session.pop('current_page_index', None)
    return redirect(url_for('index'))

@app.route('/tags', methods=['GET', 'POST'])
def tag_manager():
    # ... [Keep your existing tag_manager logic] ...
    # Copy/Paste the logic from the previous turn here if needed
    # For brevity, I assume this remains unchanged
    current_tags = load_tags()
    if request.method == 'POST':
        action = request.form.get('action')
        if action in ['add', 'edit']:
            attr_names = request.form.getlist('attr_name[]')
            attr_labels = request.form.getlist('attr_label[]')
            attr_descs = request.form.getlist('attr_desc[]')
            attr_list = []
            for i in range(len(attr_names)):
                if attr_names[i].strip():
                    attr_list.append({
                        "name": attr_names[i].strip(),
                        "label": attr_labels[i].strip() or attr_names[i].capitalize(),
                        "desc": attr_descs[i].strip() if i < len(attr_descs) else "",
                        "suggestions": [] 
                    })
            tag_data = {
                "code": request.form.get('code'),
                "label": request.form.get('label'),
                "category": request.form.get('category'),
                "color": request.form.get('color'),
                "description": request.form.get('description'),
                "attrs": attr_list
            }
            if action == 'add':
                if not any(t['code'] == tag_data['code'] for t in current_tags):
                    current_tags.append(tag_data)
            elif action == 'edit':
                for idx, t in enumerate(current_tags):
                    if t['code'] == tag_data['code']:
                        current_tags[idx] = tag_data
                        break
            save_tags(current_tags)
        elif action == 'delete':
            code = request.form.get('code')
            current_tags = [t for t in current_tags if t['code'] != code]
            save_tags(current_tags)
        return redirect(url_for('tag_manager'))
    return render_template('tags.html', tags=current_tags)

@app.route('/export_layout', methods=['GET', 'POST'])
def export_layout():
    """View or edit the TEI layout template used for export. Placeholders: {title}, {author}, {date}, {transcriber}, {country}, {settlement}, {repository}, {idno}, {material}, {objectType}, {handNote}, {language}. The body must contain an empty <div type="edition"> inside <text><body>."""
    if request.method == 'POST':
        content = request.form.get('layout_content', '')
        if content.strip():
            try:
                to_save = _indent_xml_string(content)
                with open(TEI_LAYOUT_FILE, 'w', encoding='utf-8') as f:
                    f.write(to_save)
                return redirect(url_for('export_layout'))
            except Exception as e:
                raw = _indent_xml_string(get_tei_template())
                return render_template('export_layout.html', layout_content=_safe_layout_display(raw), error=str(e))
        return redirect(url_for('export_layout'))
    raw = _indent_xml_string(get_tei_template())
    return render_template('export_layout.html', layout_content=_safe_layout_display(raw), error=None)

@app.route('/export_layout_reset', methods=['POST'])
def export_layout_reset():
    """Reset TEI layout to the built-in default."""
    try:
        if os.path.isfile(TEI_LAYOUT_FILE):
            os.remove(TEI_LAYOUT_FILE)
    except Exception:
        pass
    return redirect(url_for('export_layout'))

def _append_page_html_to_tei(tei_div, page_html, page_num, include_facs):
    """Append <pb n="page_num"/> and line content from page_html (BeautifulSoup or str) to tei_div."""
    if isinstance(page_html, str):
        soup = BeautifulSoup(page_html, 'html.parser')
    else:
        soup = page_html
    pb = etree.Element("{http://www.tei-c.org/ns/1.0}pb")
    pb.set('n', str(page_num))
    tei_div.append(pb)
    for line_div in soup.find_all(class_="line-wrapper"):
        points = line_div.get('data-points', '')
        lb = etree.Element(f"{{http://www.tei-c.org/ns/1.0}}lb")
        if include_facs and points:
            lb.set('facs', points)
        tei_div.append(lb)
        for child in line_div.recursiveChildGenerator():
            if isinstance(child, str):
                text = child.strip('\n')
                if text and len(tei_div) > 0:
                    tei_div[-1].tail = (tei_div[-1].tail or "") + text
            elif child.name == 'span' and 'tei-tag' in child.get('class', []):
                tag_name = child.get('data-tag')
                node = etree.Element(f"{{http://www.tei-c.org/ns/1.0}}{tag_name}")
                for k, v in child.attrs.items():
                    if k.startswith('data-attr-'):
                        node.set(k.replace('data-attr-', ''), v)
                node.text = child.get_text()
                tei_div.append(node)
            elif child.name == 'span' and 'ligature-highlight' in child.get('class', []):
                text = child.get_text()
                if text and len(tei_div) > 0:
                    tei_div[-1].tail = (tei_div[-1].tail or "") + text
            elif child.name == 'span' and 'ligature-mark' in child.get('class', []):
                text = child.get_text()
                hi = etree.Element("{http://www.tei-c.org/ns/1.0}hi")
                hi.set('rend', 'ligature')
                ngram = child.get('data-ngram')
                if ngram:
                    hi.set('n', ngram)
                hi.text = text
                tei_div.append(hi)


@app.route('/export', methods=['POST'])
def export_tei():
    current_page_index = request.form.get('current_page_index', type=int)
    if current_page_index is not None:
        pages = session.get('pages', [])
        if 0 <= current_page_index < len(pages):
            session['pages'][current_page_index]['html'] = request.form.get('html_content', '')
    html_content = request.form.get('html_content', '')
    export_format = request.form.get('export_format', 'positional')
    pages = session.get('pages', [])
    include_facs = export_format == 'positional'

    meta = session.get('doc_meta', {})
    defaults = {k: "???" for k in ['title','author','date','transcriber','country','settlement',
                                   'repository','idno','material','objectType','handNote','language']}
    defaults.update(meta)

    xml_str = get_tei_template().format(**defaults)
    tei_root = etree.fromstring(xml_str.encode('utf-8'))
    tei_div = tei_root.find(".//{http://www.tei-c.org/ns/1.0}div[@type='edition']")

    if not pages:
        soup = BeautifulSoup(html_content, 'html.parser')
        _append_page_html_to_tei(tei_div, soup, 1, include_facs)
    else:
        for i, page in enumerate(pages):
            page_html = page.get('html')
            if page_html:
                _append_page_html_to_tei(tei_div, page_html, i + 1, include_facs)
            else:
                lines = page.get('lines', [])
                buf = []
                for line in lines:
                    points = line.get('points', '')
                    html_part = line.get('html', '') or line.get('text', '')
                    buf.append(f'<div class="line-wrapper" data-points="{escape(points)}">{html_part}</div>')
                _append_page_html_to_tei(tei_div, ''.join(buf), i + 1, include_facs)

    out_xml = etree.tostring(tei_root, pretty_print=True, xml_declaration=True, encoding='UTF-8')
    filename = 'annotated_tei_clean.xml' if export_format == 'clean' else 'annotated_tei.xml'
    return Response(out_xml, mimetype="application/xml",
                    headers={"Content-disposition": f"attachment; filename={filename}"})

if __name__ == '__main__':
    # Web deployment: TEI_HELPER_WEB=1 or run via gunicorn (gunicorn -w 4 -b 0.0.0.0:8000 'app:app')
    if os.environ.get('TEI_HELPER_WEB'):
        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=os.environ.get('FLASK_DEBUG', '0') == '1')
    else:
        from flaskwebgui import FlaskUI
        ui = FlaskUI(app=app, server="flask")
        ui.run()