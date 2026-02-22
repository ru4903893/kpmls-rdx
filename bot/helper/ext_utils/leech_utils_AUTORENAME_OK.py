from hashlib import md5
from time import strftime, gmtime, time
from re import IGNORECASE, sub as re_sub, search as re_search
from shlex import split as ssplit
from natsort import natsorted
from os import path as ospath
from aiofiles.os import remove as aioremove, path as aiopath, mkdir, makedirs, listdir
from aioshutil import rmtree as aiormtree
from contextlib import suppress
from asyncio import create_subprocess_exec, create_task, gather, Semaphore
from asyncio.subprocess import PIPE
from telegraph import upload_file
from langcodes import Language
from html import escape as html_escape

from bot import bot_cache, LOGGER, MAX_SPLIT_SIZE, config_dict, user_data
from bot.modules.mediainfo import parseinfo
from bot.helper.ext_utils.bot_utils import cmd_exec, sync_to_async, get_readable_file_size, get_readable_time
from bot.helper.ext_utils.fs_utils import ARCH_EXT, get_mime_type
from bot.helper.ext_utils.telegraph_helper import telegraph


async def is_multi_streams(path):
    try:
        result = await cmd_exec(["ffprobe", "-hide_banner", "-loglevel", "error", "-print_format",
                                 "json", "-show_streams", path])
        if res := result[1]:
            LOGGER.warning(f'Get Video Streams: {res}')
    except Exception as e:
        LOGGER.error(f'Get Video Streams: {e}. Mostly File not found!')
        return False
    fields = eval(result[0]).get('streams')
    if fields is None:
        LOGGER.error(f"get_video_streams: {result}")
        return False
    videos = 0
    audios = 0
    for stream in fields:
        if stream.get('codec_type') == 'video':
            videos += 1
        elif stream.get('codec_type') == 'audio':
            audios += 1
    return videos > 1 or audios > 1


async def get_media_info(path, metadata=False):
    try:
        result = await cmd_exec(["ffprobe", "-hide_banner", "-loglevel", "error", "-print_format",
                                 "json", "-show_format", "-show_streams", path])
        if res := result[1]:
            LOGGER.warning(f'Media Info FF: {res}')
    except Exception as e:
        LOGGER.error(f'Media Info: {e}. Mostly File not found!')
        return (0, "", "", "") if metadata else (0, None, None)
    ffresult = eval(result[0])
    fields = ffresult.get('format')
    if fields is None:
        LOGGER.error(f"Media Info Sections: {result}")
        return (0, "", "", "") if metadata else (0, None, None)
    duration = round(float(fields.get('duration', 0)))
    if metadata:
        lang, qual, stitles = "", "", ""
        if (streams := ffresult.get('streams')) and streams[0].get('codec_type') == 'video':
            qual = int(streams[0].get('height'))
            qual = f"{480 if qual <= 480 else 540 if qual <= 540 else 720 if qual <= 720 else 1080 if qual <= 1080 else 2160 if qual <= 2160 else 4320 if qual <= 4320 else 8640}p"
            for stream in streams:
                if stream.get('codec_type') == 'audio' and (lc := stream.get('tags', {}).get('language')):
                    with suppress(Exception):
                        lc = Language.get(lc).display_name()
                    if lc not in lang:
                        lang += f"{lc}, "
                if stream.get('codec_type') == 'subtitle' and (st := stream.get('tags', {}).get('language')):
                    with suppress(Exception):
                        st = Language.get(st).display_name()
                    if st not in stitles:
                        stitles += f"{st}, "
        return duration, qual, lang[:-2], stitles[:-2]
    tags = fields.get('tags', {})
    artist = tags.get('artist') or tags.get('ARTIST') or tags.get("Artist")
    title = tags.get('title') or tags.get('TITLE') or tags.get("Title")
    return duration, artist, title


async def get_document_type(path):
    is_video, is_audio, is_image = False, False, False
    if path.endswith(tuple(ARCH_EXT)) or re_search(r'.+(\.|_)(rar|7z|zip|bin)(\.0*\d+)?$', path):
        return is_video, is_audio, is_image
    mime_type = await sync_to_async(get_mime_type, path)
    if mime_type.startswith('audio'):
        return False, True, False
    if mime_type.startswith('image'):
        return False, False, True
    if not mime_type.startswith('video') and not mime_type.endswith('octet-stream'):
        return is_video, is_audio, is_image
    try:
        result = await cmd_exec(["ffprobe", "-hide_banner", "-loglevel", "error", "-print_format",
                                 "json", "-show_streams", path])
        if res := result[1]:
            LOGGER.warning(f'Get Document Type: {res}')
    except Exception as e:
        LOGGER.error(f'Get Document Type: {e}. Mostly File not found!')
        return is_video, is_audio, is_image
    fields = eval(result[0]).get('streams')
    if fields is None:
        LOGGER.error(f"get_document_type: {result}")
        return is_video, is_audio, is_image
    for stream in fields:
        if stream.get('codec_type') == 'video':
            is_video = True
        elif stream.get('codec_type') == 'audio':
            is_audio = True
    return is_video, is_audio, is_image


async def get_audio_thumb(audio_file):
    des_dir = 'Thumbnails'
    if not await aiopath.exists(des_dir):
        await mkdir(des_dir)
    des_dir = ospath.join(des_dir, f"{time()}.jpg")
    cmd = [bot_cache['pkgs'][2], "-hide_banner", "-loglevel", "error",
           "-i", audio_file, "-an", "-vcodec", "copy", des_dir]
    status = await create_subprocess_exec(*cmd, stderr=PIPE)
    if await status.wait() != 0 or not await aiopath.exists(des_dir):
        err = (await status.stderr.read()).decode().strip()
        LOGGER.error(
            f'Error while extracting thumbnail from audio. Name: {audio_file} stderr: {err}')
        return None
    return des_dir


async def take_ss(video_file, duration=None, total=1, gen_ss=False):
    des_dir = ospath.join('Thumbnails', f"{time()}")
    await makedirs(des_dir, exist_ok=True)
    if duration is None:
        duration = (await get_media_info(video_file))[0]
    if duration == 0:
        duration = 3
    duration = duration - (duration * 2 / 100)
    cmd = [bot_cache['pkgs'][2], "-hide_banner", "-loglevel", "error", "-ss", "",
           "-i", video_file, "-vf", "thumbnail", "-frames:v", "1", des_dir]
    tstamps = {}
    thumb_sem = Semaphore(3)
    
    async def extract_ss(eq_thumb):
        async with thumb_sem:
            cmd[5] = str((duration // total) * eq_thumb)
            tstamps[f"wz_thumb_{eq_thumb}.jpg"] = strftime("%H:%M:%S", gmtime(float(cmd[5])))
            cmd[-1] = ospath.join(des_dir, f"wz_thumb_{eq_thumb}.jpg")
            task = await create_subprocess_exec(*cmd, stderr=PIPE)
            return (task, await task.wait(), eq_thumb)
    
    tasks = [extract_ss(eq_thumb) for eq_thumb in range(1, total+1)]
    status = await gather(*tasks)
    
    for task, rtype, eq_thumb in status:
        if rtype != 0 or not await aiopath.exists(ospath.join(des_dir, f"wz_thumb_{eq_thumb}.jpg")):
            err = (await task.stderr.read()).decode().strip()
            LOGGER.error(f'Error while extracting thumbnail no. {eq_thumb} from video. Name: {video_file} stderr: {err}')
            await aiormtree(des_dir)
            return None
    return (des_dir, tstamps) if gen_ss else ospath.join(des_dir, "wz_thumb_1.jpg")


async def split_file(path, size, file_, dirpath, split_size, listener, start_time=0, i=1, inLoop=False, multi_streams=True):
    if listener.suproc == 'cancelled' or listener.suproc is not None and listener.suproc.returncode == -9:
        return False
    if listener.seed and not listener.newDir:
        dirpath = f"{dirpath}/splited_files_mltb"
        if not await aiopath.exists(dirpath):
            await mkdir(dirpath)
    user_id = listener.message.from_user.id
    user_dict = user_data.get(user_id, {})
    leech_split_size = user_dict.get(
        'split_size') or config_dict['LEECH_SPLIT_SIZE']
    parts = -(-size // leech_split_size)
    if (user_dict.get('equal_splits') or config_dict['EQUAL_SPLITS'] and 'equal_splits' not in user_dict) and not inLoop:
        split_size = ((size + parts - 1) // parts) + 1000
    if (await get_document_type(path))[0]:
        if multi_streams:
            multi_streams = await is_multi_streams(path)
        duration = (await get_media_info(path))[0]
        base_name, extension = ospath.splitext(file_)
        split_size -= 5000000
        while i <= parts or start_time < duration - 4:
            parted_name = f"{base_name}.part{i:03}{extension}"
            out_path = ospath.join(dirpath, parted_name)
            cmd = [bot_cache['pkgs'][2], "-hide_banner", "-loglevel", "error", "-ss", str(start_time), "-i", path,
                   "-fs", str(split_size), "-map", "0", "-map_chapters", "-1", "-async", "1", "-strict",
                   "-2", "-c", "copy", out_path]
            if not multi_streams:
                del cmd[10]
                del cmd[10]
            if listener.suproc == 'cancelled' or listener.suproc is not None and listener.suproc.returncode == -9:
                return False
            listener.suproc = await create_subprocess_exec(*cmd, stderr=PIPE)
            code = await listener.suproc.wait()
            if code == -9:
                return False
            elif code != 0:
                err = (await listener.suproc.stderr.read()).decode().strip()
                try:
                    await aioremove(out_path)
                except Exception:
                    pass
                if multi_streams:
                    LOGGER.warning(
                        f"{err}. Retrying without map, -map 0 not working in all situations. Path: {path}")
                    return await split_file(path, size, file_, dirpath, split_size, listener, start_time, i, True, False)
                else:
                    LOGGER.warning(
                        f"{err}. Unable to split this video, if it's size less than {MAX_SPLIT_SIZE} will be uploaded as it is. Path: {path}")
                return "errored"
            out_size = await aiopath.getsize(out_path)
            if out_size > MAX_SPLIT_SIZE:
                dif = out_size - MAX_SPLIT_SIZE
                split_size -= dif + 5000000
                await aioremove(out_path)
                return await split_file(path, size, file_, dirpath, split_size, listener, start_time, i, True, )
            lpd = (await get_media_info(out_path))[0]
            if lpd == 0:
                LOGGER.error(
                    f'Something went wrong while splitting, mostly file is corrupted. Path: {path}')
                break
            elif duration == lpd:
                LOGGER.warning(
                    f"This file has been splitted with default stream and audio, so you will only see one part with less size from orginal one because it doesn't have all streams and audios. This happens mostly with MKV videos. Path: {path}")
                break
            elif lpd <= 3:
                await aioremove(out_path)
                break
            start_time += lpd - 3
            i += 1
    else:
        out_path = ospath.join(dirpath, f"{file_}.")
        listener.suproc = await create_subprocess_exec("split", "--numeric-suffixes=1", "--suffix-length=3",
                                                       f"--bytes={split_size}", path, out_path, stderr=PIPE)
        code = await listener.suproc.wait()
        if code == -9:
            return False
        elif code != 0:
            err = (await listener.suproc.stderr.read()).decode().strip()
            LOGGER.error(err)
    return True

async def format_filename(file_, user_id, dirpath=None, isMirror=False):
    """
    Build final filename (and optional caption) for leech/mirror.
    - If user has Auto Rename template (lrename) and not mirror: it overrides prefix/suffix/remname.
    - Template variables supported:
      {name} {season} {episode} {year} {resolution} {quality} {shortlang} {ott} {extension}
    """
    user_dict = user_data.get(user_id, {})
    ftag, ctag = ('m', 'MIRROR') if isMirror else ('l', 'LEECH')

    prefix = config_dict[f'{ctag}_FILENAME_PREFIX'] if (val := user_dict.get(f'{ftag}prefix', '')) == '' else val
    remname = config_dict[f'{ctag}_FILENAME_REMNAME'] if (val := user_dict.get(f'{ftag}remname', '')) == '' else val
    suffix = config_dict[f'{ctag}_FILENAME_SUFFIX'] if (val := user_dict.get(f'{ftag}suffix', '')) == '' else val
    lcaption = config_dict['LEECH_FILENAME_CAPTION'] if (val := user_dict.get('lcaption', '')) == '' else val
    lrename_tpl = user_dict.get('lrename', '') if not isMirror else ''

    # ---------- helpers ----------
    def _norm(s: str) -> str:
        return re_sub(r'[\s._-]+', ' ', s).strip()

    def _ext(name: str) -> str:
        m = re_search(r'(\.[A-Za-z0-9]{1,6})$', name)
        return m.group(1) if m else ''

    def _detect_season_episode(text: str):
        # S01E02 / s1e2
        m = re_search(r'(?i)\bS(\d{1,2})\s*E(\d{1,2})\b', text)
        if m:
            s = int(m.group(1)); e = int(m.group(2))
            return f'S{s:02d}', f'E{e:02d}'
        # 1x02
        m = re_search(r'(?i)\b(\d{1,2})x(\d{1,2})\b', text)
        if m:
            s = int(m.group(1)); e = int(m.group(2))
            return f'S{s:02d}', f'E{e:02d}'
        return '', ''

    def _detect_year(text: str) -> str:
        m = re_search(r'\b(19\d{2}|20\d{2})\b', text)
        return m.group(1) if m else ''

    def _detect_resolution(text: str) -> str:
        m = re_search(r'(?i)\b(360p|480p|540p|576p|720p|1080p|1440p|2160p|4k)\b', text)
        if not m:
            return ''
        val = m.group(1).lower()
        return '2160p' if val == '4k' else val.upper() if val.endswith('k') else val

    def _detect_quality(text: str) -> str:
        q_map = [
            (r'(?i)\bweb\s*-?\s*dl\b', 'WEB-DL'),
            (r'(?i)\bweb\s*-?\s*rip\b', 'WEBRip'),
            (r'(?i)\bbluray\b|\bbdrip\b', 'BluRay'),
            (r'(?i)\bhdrip\b', 'HDRip'),
            (r'(?i)\bhdtv\b', 'HDTV'),
            (r'(?i)\bdvdrip\b', 'DVDRip'),
            (r'(?i)\bcam\b|\bhdcam\b', 'CAM'),
        ]
        for pat, out in q_map:
            if re_search(pat, text):
                return out
        return ''

    def _detect_ott(text: str) -> str:
        # user wants only NF / AMZN short
        if re_search(r'(?i)\bNF\b|NETFLIX', text):
            return 'NF'
        if re_search(r'(?i)\bAMZN\b|AMAZON', text):
            return 'AMZN'
        return ''

    def _detect_shortlang(text: str) -> str:
        t = text.lower()
        has_hin = bool(re_search(r'\bhin(di)?\b', t))
        has_eng = bool(re_search(r'\beng(lish)?\b', t))
        has_tam = bool(re_search(r'\btam(il)?\b', t))
        has_tel = bool(re_search(r'\btel(ugu)?\b', t))
        langs = []
        if has_hin: langs.append('Hindi')
        if has_eng: langs.append('English')
        if has_tam: langs.append('Tamil')
        if has_tel: langs.append('Telugu')
        if len(langs) >= 2:
            return 'Dual Audio ' + ' '.join(langs[:2])
        if langs:
            return langs[0]
        return ''

    def _clean_title(raw: str) -> str:
        # drop @tags and brackets first
        raw = re_sub(r'@\w+', '', raw)
        raw = re_sub(r'\[.*?\]|\(.*?\)', ' ', raw)
        raw = _norm(raw)

        # split into tokens; stop when we hit technical tags
        stop_pat = re_compile(
            r'(?i)^(s\d{1,2}e\d{1,2}|\d{1,2}x\d{1,2}|19\d{2}|20\d{2}|'
            r'360p|480p|540p|576p|720p|1080p|1440p|2160p|4k|'
            r'webdl|web-dl|webrip|web-rip|bluray|bdrip|hdrip|hdtv|dvdrip|cam|'
            r'x264|x265|hevc|aac|ddp?5\.?1|atmos|10bit|8bit|hdr10?|dv|'
            r'vegamovies|yts|psa|rarbg|torrent|mkv)$'
        )
        tokens = raw.split()
        keep = []
        for tok in tokens:
            if stop_pat.match(tok):
                break
            keep.append(tok)
        title = ' '.join(keep).strip()
        return title.title() if title else raw.title()

    # ---------- normalize original filename ----------
    original = file_.strip()

    # strip obvious URLs
    original = re_sub(r'(?i)\bhttps?://\S+|\bwww\.\S+', '', original).strip()

    ext = _ext(original)
    base = original[:-len(ext)] if ext else original

    # metadata extraction from base
    season, episode = _detect_season_episode(base)
    year = _detect_year(base)
    resolution = _detect_resolution(base)
    quality = _detect_quality(base)
    ott = _detect_ott(base)
    shortlang = _detect_shortlang(base)
    name = _clean_title(base)

    # ---------- apply template (leech only) ----------
    if lrename_tpl:
        repl = {
            'name': name,
            'season': season,
            'episode': episode,
            'year': year,
            'resolution': resolution,
            'quality': quality,
            'ott': ott,
            'shortlang': shortlang,
            'extension': ext or _ext(original) or '',
        }
        try:
            final_name = lrename_tpl.format(**repl)
        except Exception:
            # if template invalid, fall back to safe default
            final_name = f"{name} {season}{episode} {year} {resolution} {quality} {shortlang}{ext}".strip()
        final_name = _norm(final_name).replace(' .', '.')
        # keep extension if missing
        if ext and not final_name.lower().endswith(ext.lower()):
            final_name = final_name + ext

        # caption: if user has lcaption, apply placeholders too, else use filename as caption
        if lcaption:
            try:
                cap = lcaption.format(**repl, filename=final_name)
            except Exception:
                cap = lcaption
        else:
            cap = final_name
        cap = html_escape(cap) if isinstance(cap, str) else cap

        # If dirpath given, return full path
        if dirpath:
            return (final_name, cap, f"{dirpath}/{final_name}")
        return (final_name, cap, final_name)

    # ---------- legacy behaviour (prefix/remname/suffix) ----------
    # Remove remname patterns
    if remname:
        try:
            file_ = re_sub(remname, '', original, flags=IGNORECASE).strip()
        except Exception:
            file_ = original
    else:
        file_ = original

    file_ = _norm(file_)
    if prefix:
        file_ = _norm(f"{prefix} {file_}")
    if suffix:
        file_ = _norm(f"{file_} {suffix}")
    # restore extension if lost
    if ext and not file_.lower().endswith(ext.lower()):
        file_ = file_ + ext

    cap = file_
    if lcaption:
        try:
            cap = lcaption.format(filename=file_)
        except Exception:
            cap = lcaption
    cap = html_escape(cap) if isinstance(cap, str) else cap

    if dirpath:
        return (file_, cap, f"{dirpath}/{file_}")
    return (file_, cap, file_)


async def get_ss(up_path, ss_no):
    thumbs_path, tstamps = await take_ss(up_path, total=min(ss_no, 250), gen_ss=True)
    th_html = f"📌 <h4>{ospath.basename(up_path)}</h4><br>📇 <b>Total Screenshots:</b> {ss_no}<br><br>"
    up_sem = Semaphore(25)
    async def telefile(thumb):
        async with up_sem:
            tele_id = await sync_to_async(upload_file, ospath.join(thumbs_path, thumb))
            return tele_id[0], tstamps[thumb]
    tasks = [telefile(thumb) for thumb in natsorted(await listdir(thumbs_path))]
    results = await gather(*tasks)
    th_html += ''.join(f'<img src="https://graph.org{tele_id}"><br><pre>Screenshot at {stamp}</pre>' for tele_id, stamp in results)
    await aiormtree(thumbs_path)
    link_id = (await telegraph.create_page(title="ScreenShots X", content=th_html))["path"]
    return f"https://graph.org/{link_id}"


async def get_mediainfo_link(up_path):
    stdout, __, _ = await cmd_exec(ssplit(f'mediainfo "{up_path}"'))
    tc = f"📌 <h4>{ospath.basename(up_path)}</h4><br><br>"
    if len(stdout) != 0:
        tc += parseinfo(stdout)
    link_id = (await telegraph.create_page(title="MediaInfo X", content=tc))["path"]
    return f"https://graph.org/{link_id}"


def get_md5_hash(up_path):
    md5_hash = md5()
    with open(up_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            md5_hash.update(byte_block)
        return md5_hash.hexdigest()
