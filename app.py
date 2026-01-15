import os
import json
import uuid
import re
from flask import Flask, render_template, request, Response, redirect, url_for, session
from lxml import etree
from bs4 import BeautifulSoup
from flaskwebgui import FlaskUI

app = Flask(__name__)
app.secret_key = 'tei_secret_key'

# --- CONFIGURATION ---
UPLOAD_FOLDER = 'uploads'
TAGS_FILE = 'tags.json'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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

# Updated Skeleton based on user requirements
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
<name>TEI Helper App</name>
</respStmt>
</titleStmt>
<publicationStmt>
<p>Transcribed using TEI Helper.</p>
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
<layout>
</layout>
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
<div type="edition">
</div>
</body>
</text>
</TEI>
"""

# --- ROUTES ---

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        uploaded_file = request.files.get('file')
        if uploaded_file:
            filename = f"{uuid.uuid4()}_{uploaded_file.filename}"
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            uploaded_file.save(filepath)
            session['current_file'] = filepath
            
            # Detect File Type (PageXML vs TEI)
            try:
                tree = etree.parse(filepath)
                root = tree.getroot()
                
                # If TEI -> Parse Metadata & Body for re-editing
                if 'TEI' in root.tag or 'ns/1.0' in root.tag:
                    return parse_tei_import(tree)
                
                # If PageXML -> Default Flow
                else:
                    session['doc_meta'] = {} # Reset metadata
                    return redirect(url_for('doc_info'))
            
            except Exception as e:
                return f"Error parsing file: {e}", 400

    if 'current_file' in session and os.path.exists(session['current_file']):
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

    return redirect(url_for('doc_info'))

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
    file_path = session.get('current_file')
    if not file_path or not os.path.exists(file_path):
        return redirect(url_for('index'))

    # If we have imported lines from TEI, use them
    if 'imported_lines' in session:
        return render_template('editor.html', 
                             lines=session['imported_lines'], 
                             img_url="", 
                             orig_width=0, orig_height=0, 
                             tags=load_tags())

    # Otherwise, Parse PageXML (Standard Flow)
    try:
        tree = etree.parse(file_path)
    except:
        return redirect(url_for('index'))

    img_url = ""
    meta = tree.xpath('//*[local-name()="TranskribusMetadata"]')
    if meta: img_url = meta[0].get('imgUrl')

    orig_w, orig_h = 0, 0
    page = tree.xpath('//*[local-name()="Page"]')
    if page:
        orig_w = int(page[0].get('imageWidth'))
        orig_h = int(page[0].get('imageHeight'))

    lines_data = []
    text_lines = tree.xpath('//*[local-name()="TextLine"]')
    for i, node in enumerate(text_lines):
        t_node = node.xpath('.//*[local-name()="Unicode"]/text()')
        text = t_node[0] if t_node else ""
        c_node = node.xpath('.//*[local-name()="Coords"]')
        points = c_node[0].get('points') if c_node else ""
        lines_data.append({'id': i, 'text': text, 'points': points}) # No 'html' initially

    tags = load_tags()
    return render_template('editor.html', lines=lines_data, img_url=img_url, 
                           orig_width=orig_w, orig_height=orig_h, tags=tags)

@app.route('/close')
def close_file():
    session.pop('current_file', None)
    session.pop('doc_meta', None)
    session.pop('imported_lines', None)
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

@app.route('/export', methods=['POST'])
def export_tei():
    html_content = request.form.get('html_content')
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. Fill Metadata Template
    meta = session.get('doc_meta', {})
    # Provide defaults to prevent KeyErrors
    defaults = {k: "???" for k in ['title','author','date','transcriber','country','settlement',
                                   'repository','idno','material','objectType','handNote','language']}
    defaults.update(meta)
    
    xml_str = TEI_TEMPLATE.format(**defaults)
    tei_root = etree.fromstring(xml_str.encode('utf-8'))
    tei_div = tei_root.find(".//{http://www.tei-c.org/ns/1.0}div[@type='edition']")

    # 2. Convert HTML Body to TEI
    for line_div in soup.find_all(class_="line-wrapper"):
        # We append points to the <lb> to allow future re-import with coords
        points = line_div.get('data-points', '')
        lb = etree.Element(f"{{http://www.tei-c.org/ns/1.0}}lb")
        if points: lb.set('facs', points) # Storing points in 'facs' for persistence
        tei_div.append(lb)

        for child in line_div.recursiveChildGenerator():
            if isinstance(child, str):
                text = child.strip('\n')
                if text:
                    if len(tei_div) > 0:
                        tei_div[-1].tail = (tei_div[-1].tail or "") + text
            elif child.name == 'span' and 'tei-tag' in child.get('class', []):
                tag_name = child.get('data-tag')
                node = etree.Element(f"{{http://www.tei-c.org/ns/1.0}}{tag_name}")
                for k, v in child.attrs.items():
                    if k.startswith('data-attr-'):
                        node.set(k.replace('data-attr-', ''), v)
                node.text = child.get_text()
                tei_div.append(node)

    out_xml = etree.tostring(tei_root, pretty_print=True, xml_declaration=True, encoding='UTF-8')
    return Response(out_xml, mimetype="application/xml", 
                    headers={"Content-disposition": "attachment; filename=annotated_tei.xml"})

if __name__ == '__main__':
    ui = FlaskUI(
        app=app,
        server="flask",
    )
    ui.run()