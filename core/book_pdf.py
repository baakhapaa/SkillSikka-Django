"""Isolated, time-bounded PDF text extraction for explicitly authored ranges.

Invoked only by the book service; it never invents chapter boundaries or runs PDF
actions. stdout is a bounded JSON result. No Django/database access in the child.
"""
import json
import sys
import logging
import warnings


def main():
    try:
        logging.disable(logging.CRITICAL)
        warnings.simplefilter('ignore')
        if sys.platform != 'win32':
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
            resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        from pypdf import PdfReader
        path, operation = sys.argv[1], sys.argv[2]
        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            raise ValueError('Encrypted PDF.')
        page_count = len(reader.pages)
        if not 1 <= page_count <= 10000:
            raise ValueError('Unsupported page count.')
        if operation == 'inspect':
            print(json.dumps({'page_count': page_count}))
            return
        start, end = int(sys.argv[3]), int(sys.argv[4])
        if operation != 'extract' or not 1 <= start <= end <= page_count or end-start >= 20:
            raise ValueError('Unsupported PDF or page range.')
        parts = []
        for number in range(start-1, end):
            text = reader.pages[number].extract_text() or ''
            parts.append(text)
            if sum(map(len, parts)) > 200_000:
                raise ValueError('Text limit exceeded.')
        print(json.dumps({'page_count': page_count, 'content': '\n\n'.join(parts)}))
    except Exception:
        # Do not leak parser errors or filesystem paths to the parent/API.
        print(json.dumps({'error': 'PDF text extraction unavailable. Use the protected PDF viewer or author text manually.'}))


if __name__ == '__main__':
    main()
