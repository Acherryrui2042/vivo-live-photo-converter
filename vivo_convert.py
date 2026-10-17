import json
import os
import struct
import sys
import uuid
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / '转换结果'
IMAGES = {'.jpg', '.jpeg'}
VIDEOS = {'.mp4'}
KEY = 'com.android.camera.livephoto'


def boxes(data):
    pos = 0
    while pos < len(data):
        if pos + 8 > len(data):
            raise ValueError('MP4 文件头不完整')
        size, kind = struct.unpack_from('>I4s', data, pos)
        header = 8
        if size == 1:
            if pos + 16 > len(data):
                raise ValueError('MP4 扩展长度不完整')
            size = struct.unpack_from('>Q', data, pos + 8)[0]
            header = 16
        elif size == 0:
            size = len(data) - pos
        if size < header or pos + size > len(data):
            raise ValueError('MP4 数据长度不正确')
        yield pos, size, kind, header
        pos += size


def load_profile():
    profile = json.loads((BASE / 'vivo_profile.json').read_text(encoding='utf-8'))
    old_id = profile['pair_id'].encode('ascii')
    trailer = bytes.fromhex(profile['jpeg_trailer_hex'])
    extension = bytes.fromhex(profile['mp4_extension_hex'])
    if len(old_id) != 28 or trailer.count(old_id) != 2 or extension.count(old_id) != 2:
        raise ValueError('配对模板损坏，请保留原始 vivo_profile.json 文件')
    if list(boxes(extension))[0][2] != b'uuid':
        raise ValueError('视频模板结构错误')
    return old_id, trailer, extension


def collect(arguments):
    found = {}
    notes = []
    output_root = OUTPUT.resolve()
    for argument in arguments:
        path = Path(argument.strip('"')).resolve()
        if not path.exists():
            notes.append('路径不存在：' + str(path))
            continue
        candidates = path.rglob('*') if path.is_dir() else [path]
        for item in candidates:
            if not item.is_file():
                continue
            resolved = item.resolve()
            if output_root == resolved or output_root in resolved.parents:
                continue
            if item.suffix.lower() in IMAGES | VIDEOS:
                found[os.path.normcase(str(resolved))] = resolved
            elif not path.is_dir():
                notes.append('不支持此格式（仅 JPG/JPEG + MP4）：' + str(item))
    return sorted(found.values(), key=lambda p: str(p).lower()), notes


def pair_files(files):
    images = [p for p in files if p.suffix.lower() in IMAGES]
    videos = [p for p in files if p.suffix.lower() in VIDEOS]
    if len(images) == 1 and len(videos) == 1:
        return [(images[0], videos[0])], []
    groups = {}
    for path in files:
        key = (os.path.normcase(str(path.parent)), path.stem.casefold())
        group = groups.setdefault(key, {'images': [], 'videos': []})
        group['images' if path.suffix.lower() in IMAGES else 'videos'].append(path)
    pairs, notes = [], []
    for group in groups.values():
        if len(group['images']) == 1 and len(group['videos']) == 1:
            pairs.append((group['images'][0], group['videos'][0]))
        else:
            notes.append('跳过：找不到唯一的同目录同名配对：' + '；'.join(str(p) for p in group['images'] + group['videos']))
    return pairs, notes


def convert(photo_path, video_path, target, profile):
    photo = photo_path.read_bytes()
    video = video_path.read_bytes()
    if not photo.startswith(b'\xff\xd8') or not photo.endswith(b'\xff\xd9'):
        raise ValueError('需要普通 JPG 原图；已有动态尾部或损坏的 JPG 不处理')
    entries = list(boxes(video))
    if not entries or entries[0][2] != b'ftyp' or not any(e[2] == b'moov' for e in entries):
        raise ValueError('不是完整的 MP4 视频（缺少 ftyp 或 moov）')
    if not any(e[2] == b'mdat' for e in entries):
        raise ValueError('视频缺少媒体数据')
    if any(kind == b'uuid' and video[pos + header:pos + header + 16] == b'vivoMediaExtInfo'
           for pos, size, kind, header in entries):
        raise ValueError('视频已带 vivo 实况配对信息，请使用未转换的原视频')
    old_id, trailer, extension = profile
    new_id = uuid.uuid4().hex[:28].encode('ascii')
    last_pos, last_size, last_kind, last_header = entries[-1]
    if struct.unpack_from('>I', video, last_pos)[0] == 0:
        if last_size > 0xffffffff:
            raise ValueError('不支持超过 4GB 的开放长度 MP4 数据块')
        video = video[:last_pos] + struct.pack('>I', last_size) + video[last_pos + 4:]
    jpg_data = photo + trailer.replace(old_id, new_id)
    mp4_data = video + extension.replace(old_id, new_id)
    if jpg_data[-len(trailer):].count(new_id) != 2 or mp4_data[-len(extension):].count(new_id) != 2:
        raise ValueError('输出关联 ID 校验失败')
    list(boxes(mp4_data))
    name = photo_path.stem + '_vivo_' + new_id[:8].decode('ascii')
    jpg = target / (name + '.jpg')
    mp4 = target / (name + '.mp4')
    created = []
    try:
        for path, data in [(jpg, jpg_data), (mp4, mp4_data)]:
            with path.open('xb') as stream:
                created.append(path)
                stream.write(data)
        if jpg.stat().st_size != len(jpg_data) or mp4.stat().st_size != len(mp4_data):
            raise OSError('输出文件大小校验失败')
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return jpg, mp4


def pick_files():
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    try:
        return list(filedialog.askopenfilenames(
            title='选择需要配对的 JPG 图片和 MP4 视频（可多选）',
            filetypes=[('照片与视频', '*.jpg *.jpeg *.mp4'), ('所有文件', '*.*')]))
    finally:
        root.destroy()


def main(arguments):
    print('vivo / iQOO 双文件动态照片转换工具')
    print('已在 iQOO Neo9 的一个系统环境中验证样本方案；其他机型未验证。')
    print('支持 JPG/JPEG + MP4，不改变画面编码，不删除原文件。\n')
    if not arguments:
        arguments = pick_files()
        if not arguments:
            print('未选择文件。也可以把图片、视频或文件夹拖到“拖入图片视频转换.bat”上。')
            return 0
    profile = load_profile()
    files, notes = collect(arguments)
    pairs, pairing_notes = pair_files(files)
    notes += pairing_notes
    paired_paths = {path for pair in pairs for path in pair}
    skipped = sum(path not in paired_paths for path in files) + len(notes) - len(pairing_notes)
    for note in notes:
        print(note)
    if not pairs:
        message = '没有可转换配对。单组可用不同文件名；批量需在同目录保持 JPG 与 MP4 主文件名一致。'
        print('\n' + message)
        notes.append(message)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / (datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
    target.mkdir()
    lines = list(notes)
    success = failed = 0
    for photo, video in pairs:
        try:
            jpg, mp4 = convert(photo, video, target, profile)
            text = '成功：{} + {}\n  JPG：{}\n  MP4：{}'.format(photo, video, jpg.name, mp4.name)
            success += 1
        except Exception as error:
            text = '失败：{} + {}\n  原因：{}'.format(photo, video, error)
            failed += 1
        print(text)
        lines.append(text)
    summary = '\n完成：成功 {} 组，失败 {} 组，跳过 {} 个文件或无效输入。\n输出目录：{}\n请将每组 JPG 和 MP4 一起复制到手机同一文件夹，保持同名。'.format(success, failed, skipped, target)
    print(summary)
    lines.append(summary)
    (target / '转换记录.txt').write_text('\n'.join(lines), encoding='utf-8-sig')
    if success and hasattr(os, 'startfile') and not os.environ.get('VIVO_NO_OPEN'):
        try:
            os.startfile(str(target))
        except OSError:
            pass
    if failed or not pairs:
        return 1
    return 2 if skipped else 0


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as error:
        print('转换未完成：' + str(error))
        sys.exit(1)
