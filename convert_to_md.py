import os
import re
import glob
import gc
from multiprocessing import Pool
from tqdm import tqdm
from selectolax.parser import HTMLParser

# ─── Configuration ────────────────────────────────────────────────────────────
RAW_HTML_PATH  = os.path.expanduser("~/Desktop/SEC_AI_AGENT/data/raw_html")
MD_OUTPUT_PATH = os.path.expanduser("~/Desktop/SEC_AI_AGENT/data/md_files")
CPU_WORKERS    = 16      # leave some cores free
MIN_OUTPUT_CHARS = 200
MAX_FILE_SIZE_MB = 20    # skip files larger than this (likely malformed)
FORCE_RERUN    = True    # set True to re-convert already-converted files


def strip_ixbrl_header(html: str) -> str:
    """Remove iXBRL hidden sections before parsing."""
    # Use a non-backtracking approach: find tag boundaries manually
    for tag in ('ix:header', 'ix:hidden'):
        open_tag  = f'<{tag}'
        close_tag = f'</{tag}'
        while True:
            start = html.lower().find(open_tag.lower())
            if start == -1:
                break
            end = html.lower().find(close_tag.lower(), start)
            if end == -1:
                html = html[:start]
                break
            end = html.find('>', end) + 1
            html = html[:start] + html[end:]
    return html


def is_section_header(line: str) -> bool:
    """Detect SEC filing section headers to convert to markdown ## headings."""
    # SEC standard: "Item 1.", "Item 1A.", "ITEM 2B." etc.
    if re.match(r'^item\s+\d+[a-z]?\b', line, re.IGNORECASE) and len(line) < 120:
        return True
    # PART I / PART II / PART III / PART IV
    if re.match(r'^part\s+[ivxlIVXL]+\b', line, re.IGNORECASE) and len(line) < 80:
        return True
    # ALL CAPS lines: short, mostly alpha, not just numbers
    if (line == line.upper()
            and len(line) <= 80
            and sum(c.isalpha() for c in line) >= 4
            and not re.match(r'^[\d\s\.\,\-\(\)]+$', line)):
        return True
    return False


def extract_text(html_content: str) -> str:
    """Extract readable text from an SEC HTML filing."""
    html_content = strip_ixbrl_header(html_content)

    tree = HTMLParser(html_content)

    for tag in tree.css('script, style, noscript, iframe, meta, link'):
        tag.decompose()

    body = tree.body if tree.body else tree.root
    if not body:
        return ''

    text = body.text(separator='\n', strip=True)

    lines = []
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            lines.append('')
            continue
        if re.match(r'^[\s\-_|=*#\.]+$', line) or len(line) < 3:
            continue
        if is_section_header(line):
            lines.append(f'## {line}')
        else:
            lines.append(line)

    result = '\n'.join(lines)
    return re.sub(r'\n{3,}', '\n\n', result).strip()


def is_junk(text: str) -> bool:
    """Detect XBRL/XML data masquerading as text."""
    if not text or len(text) < 50:
        return True

    sample = text[:1000]

    xbrl_patterns = [
        'xbrli:', 'us-gaap:', 'iso4217:', 'dei:', 'fasb.org',
        'ix:nonfraction', 'ix:nonnumeric', 'xbrl', 'xmlns:',
        'http://fasb', 'http://xbrl', 'http://www.xbrl',
    ]
    if sum(1 for p in xbrl_patterns if p.lower() in sample.lower()) >= 2:
        return True

    words = sample.split()
    if not words:
        return True
    avg_word_len = sum(len(w) for w in words[:30]) / max(len(words[:30]), 1)
    if avg_word_len > 20:
        return True

    english = sum(1 for w in words if re.match(r"^[a-zA-Z,\.\-\'\"!?;:()]+$", w))
    if len(words) > 10 and english / len(words) < 0.15:
        return True

    return False


def convert_file(filepath):
    """Convert a single HTML file to text. Returns a status string."""
    try:
        # Skip oversized files
        file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
        if file_size_mb > MAX_FILE_SIZE_MB:
            return 'too_large'

        rel_path = os.path.relpath(filepath, RAW_HTML_PATH)
        out_path  = os.path.join(MD_OUTPUT_PATH, rel_path)
        for ext in ['.html', '.htm', '.txt']:
            if out_path.lower().endswith(ext):
                out_path = out_path[:-len(ext)] + '.md'
                break

        # Skip if already converted and clean (unless forced)
        if not FORCE_RERUN and os.path.exists(out_path) and os.path.getsize(out_path) > MIN_OUTPUT_CHARS:
            with open(out_path, 'r', encoding='utf-8', errors='ignore') as f:
                existing = f.read(1000)
            if not is_junk(existing):
                return 'skipped'
            else:
                os.remove(out_path)

        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            html_content = f.read()

        if len(html_content) < 100:
            return 'empty'

        text = extract_text(html_content)

        if is_junk(text):
            return 'xbrl_junk'

        if len(text) < MIN_OUTPUT_CHARS:
            return 'too_short'

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(text)

        return 'success'

    except Exception as e:
        return f'failed: {e}'


def main():
    print('=' * 60)
    print('SEC Filing HTML -> Text Converter')
    print('=' * 60)

    print(f'\nScanning {RAW_HTML_PATH} ...')
    all_files = []
    for ext in ['*.html', '*.htm', '*.txt']:
        all_files.extend(glob.glob(os.path.join(RAW_HTML_PATH, '**', ext), recursive=True))
    all_files = [f for f in all_files if os.path.isfile(f)]
    print(f'Found {len(all_files)} files\n')

    results = {'success': 0, 'skipped': 0, 'empty': 0,
               'xbrl_junk': 0, 'too_short': 0, 'too_large': 0, 'failed': 0}

    # Process in batches to keep memory clean
    BATCH = 2000
    for batch_start in range(0, len(all_files), BATCH):
        batch = all_files[batch_start:batch_start + BATCH]

        with Pool(processes=CPU_WORKERS, maxtasksperchild=20) as pool:
            for status in tqdm(
                pool.imap_unordered(convert_file, batch, chunksize=5),
                total=len(batch),
                desc=f'Batch {batch_start//BATCH + 1}/{(len(all_files)-1)//BATCH + 1}'
            ):
                key = status if status in results else 'failed'
                results[key] += 1

        gc.collect()

    print(f"\n{'=' * 60}")
    print(f"SUCCESS (converted):     {results['success']}")
    print(f"SKIPPED (already good):  {results['skipped']}")
    print(f"XBRL JUNK (unreadable):  {results['xbrl_junk']}")
    print(f"EMPTY (no content):      {results['empty']}")
    print(f"TOO SHORT (<{MIN_OUTPUT_CHARS} chars): {results['too_short']}")
    print(f"TOO LARGE (>{MAX_FILE_SIZE_MB}MB):      {results['too_large']}")
    print(f"FAILED (errors):         {results['failed']}")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
