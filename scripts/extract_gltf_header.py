import struct
import json
import os

def extract_glb_json(glb_path, output_path):
    """
    Parses a GLB (Binary GLTF) file and extracts its JSON chunk.
    Saves the JSON to output_path.
    """
    if not os.path.exists(glb_path):
        print(f"Error: {glb_path} not found.")
        return False

    try:
        with open(glb_path, 'rb') as f:
            # Read header (12 bytes)
            # 4 bytes: magic ("glTF")
            # 4 bytes: version
            # 4 bytes: total length
            magic = f.read(4)
            if magic != b'glTF':
                print("Error: Not a valid glTF/GLB file (magic mismatch).")
                return False
            
            version = struct.unpack('<I', f.read(4))[0]
            total_length = struct.unpack('<I', f.read(4))[0]
            
            # Read Chunk 0 header (8 bytes)
            # 4 bytes: chunk length
            # 4 bytes: chunk type ("JSON" = 0x4E4F534A)
            chunk_length = struct.unpack('<I', f.read(4))[0]
            chunk_type = f.read(4)
            
            if chunk_type != b'JSON':
                print(f"Error: Chunk 0 is not JSON (found {chunk_type}).")
                return False
            
            # Read JSON content
            json_data = f.read(chunk_length).decode('utf-8')
            
            # Clean up any trailing null bytes (padding)
            json_data = json_data.strip('\x00')
            
            # Parse and re-serialize to ensure valid JSON and pretty formatting
            data = json.loads(json_data)
            with open(output_path, 'w') as out:
                json.dump(data, out, indent=4)
            
            print(f"Successfully extracted GLTF JSON header to {output_path}")
            return True
            
    except Exception as e:
        print(f"Error extracting GLTF header: {e}")
        return False

if __name__ == "__main__":
    # When run as a script, assume we are in 'scripts/' and the model is in the root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    
    glb_file = os.path.join(project_root, "robot_arm_sha.glb")
    header_file = os.path.join(project_root, "gltf_header.json")
    
    extract_glb_json(glb_file, header_file)
