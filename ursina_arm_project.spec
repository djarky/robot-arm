import os
import struct
import json
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

# --- Automate GLTF Header Extraction ---
def run_header_extraction():
    glb_path = 'robot_arm_sha.glb'
    output_path = 'gltf_header.json'
    if not os.path.exists(glb_path):
        return
    try:
        with open(glb_path, 'rb') as f:
            # Skip GLB header (12 bytes)
            f.seek(12)
            # Read Chunk 0 length and type
            chunk_length = struct.unpack('<I', f.read(4))[0]
            chunk_type = f.read(4)
            if chunk_type == b'JSON':
                json_data = f.read(chunk_length).decode('utf-8').strip('\x00')
                data = json.loads(json_data)
                with open(output_path, 'w') as out:
                    json.dump(data, out, indent=4)
                print(f"Spec-Build: Successfully updated {output_path} from {glb_path}")
    except Exception as e:
        print(f"Spec-Build Warning: Failed to extract GLTF header: {e}")

run_header_extraction()
# ---------------------------------------

block_cipher = None

datas = [
    ('robot_arm_sha.glb', '.'),
    ('texture.png', '.'),
    ('config.json', '.'),
    ('poses.json', '.'),
    ('animations.json', '.'),
    ('gltf_header.json', '.'),
    ('hand_landmarker.task', '.'),
    ('pose_landmarker.task', '.'),
    ('arduino_control/*', 'arduino_control'),
    ('gui/*', 'gui'),
]

# Explicitly collect panda3d and ursina assets
datas += collect_data_files('ursina')
datas += collect_data_files('panda3d')

# Load GLTF and PBR entry points and metadata
datas += copy_metadata('panda3d-gltf')
datas += copy_metadata('panda3d-simplepbr')
datas += collect_data_files('gltf')
datas += collect_data_files('simplepbr')

# Explicitly collect panda3d dynamic libraries (libpandagl, libp3dwindow, etc.)
binaries = collect_dynamic_libs('panda3d')
binaries += collect_dynamic_libs('ursina')

hiddenimports = [
    'ursina',
    'panda3d',
    'gltf',
    'simplepbr',
    'serial',
    'serial.tools.list_ports',
    'cv2',
    'mediapipe',
]

# We define two separate Analysis objects for dual executables

a_gui = Analysis(
    ['gui_main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

a_sim = Analysis(
    ['sim_3d.py'],
    pathex=[],
    binaries=binaries,
    datas=datas, # Sharing same datas
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data, cipher=block_cipher)
pyz_sim = PYZ(a_sim.pure, a_sim.zipped_data, cipher=block_cipher)

exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name='UrsinaArmSimulator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True, # Set to True to see stdout/stderr logs
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

exe_sim = EXE(
    pyz_sim,
    a_sim.scripts,
    [],
    exclude_binaries=True,
    name='sim_3d',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.zipfiles,
    a_gui.datas,
    exe_sim,
    a_sim.binaries,
    a_sim.zipfiles,
    a_sim.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='UrsinaArmSimulator',
)
