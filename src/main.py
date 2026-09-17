import os
import json
import base64
import tempfile
import zipfile
from PIL import Image
import pikepdf

def main(context):
    # 1. Handle CORS for browser requests
    if context.req.method == 'OPTIONS':
        return context.res.send('', 200, {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, x-appwrite-key',
        })

    if context.req.method != 'POST':
        return context.res.json({'error': 'Method not allowed'}, 405, {'Access-Control-Allow-Origin': '*'})

    try:
        # 2. Parse Payload safely
        body = context.req.body_json if hasattr(context.req, 'body_json') and context.req.body_json else {}
        if not body and context.req.body:
            body = json.loads(context.req.body) if isinstance(context.req.body, str) else context.req.body

        file_b64 = body.get('file_b64', '')
        file_name = body.get('file_name', 'file.tmp').lower()

        if not file_b64:
            return context.res.json({'error': 'Missing file_b64 in payload'}, 400, {'Access-Control-Allow-Origin': '*'})

        # 3. Clean and fix Base64 string padding
        if ',' in file_b64:
            file_b64 = file_b64.split(',', 1)[1]
        file_b64 = ''.join(file_b64.split())

        remainder = len(file_b64) % 4
        if remainder == 1:
            file_b64 = file_b64[:-1]
        elif remainder > 1:
            file_b64 += '=' * (4 - remainder)

        # 4. Decode File & Create Temporary Paths
        try:
            file_data = base64.b64decode(file_b64)
        except Exception as b64_err:
            return context.res.json({'error': f'Invalid Base64 data: {str(b64_err)}'}, 400, {'Access-Control-Allow-Origin': '*'})

        ext = os.path.splitext(file_name)[1]

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_in:
            temp_in.write(file_data)
            temp_in_path = temp_in.name
        
        temp_out_path = temp_in_path + "_clean"

        try:
            metadata_removed = []

            # 5A. Handle PDFs (Safely removes docinfo without breaking structure)
            if ext == ".pdf":
                pdf = pikepdf.Pdf.open(temp_in_path)
                if hasattr(pdf, 'docinfo'):
                    del pdf.docinfo
                    metadata_removed.append("Document Info & Author Data")
                pdf.save(temp_out_path)

            # 5B. Handle Images (Strips EXIF, GPS, Device ID)
            elif ext in [".jpg", ".jpeg", ".png"]:
                img = Image.open(temp_in_path)
                fmt = img.format if img.format else 'PNG'
                # Saving without 'exif' drops all hidden image data
                img.save(temp_out_path, format=fmt)
                metadata_removed.extend(["EXIF Data", "GPS Coordinates", "Device Info"])

            # 5C. Handle Office Docs (Strips hidden XML tracking properties)
            elif ext in [".docx", ".xlsx", ".pptx"]:
                with zipfile.ZipFile(temp_in_path, 'r') as zin:
                    with zipfile.ZipFile(temp_out_path, 'w') as zout:
                        for item in zin.infolist():
                            # Drop the metadata property folders inside the zip structure
                            if not item.filename.startswith('docProps/'):
                                zout.writestr(item, zin.read(item.filename))
                            else:
                                if "Hidden Core Properties" not in metadata_removed:
                                    metadata_removed.append("Hidden Core Properties")

            else:
                return context.res.json({'error': f'Unsupported file type: {ext}'}, 400, {'Access-Control-Allow-Origin': '*'})

            # 6. Read the clean file back into memory
            with open(temp_out_path, "rb") as f:
                clean_data = f.read()

            clean_b64 = base64.b64encode(clean_data).decode('utf-8')

            return context.res.json({
                'success': True,
                'file_b64': clean_b64,
                'metadata_removed': list(set(metadata_removed)) if metadata_removed else ["No metadata found"],
                'sizeSaved': len(file_data) - len(clean_data)
            }, 200, {'Access-Control-Allow-Origin': '*'})

        finally:
            # 7. PRIVACY GUARANTEE: Wipe files immediately
            if os.path.exists(temp_in_path):
                os.remove(temp_in_path)
            if os.path.exists(temp_out_path):
                os.remove(temp_out_path)

    except Exception as e:
        context.error(f"Processing Error: {str(e)}")
        return context.res.json({'error': f'Server processing failed: {str(e)}'}, 500, {'Access-Control-Allow-Origin': '*'})
