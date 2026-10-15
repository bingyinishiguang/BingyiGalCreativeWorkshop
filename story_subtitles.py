"""Editable SRT sidecar aligned with the same integer frames as the video."""
def timestamp(frame, fps=30):
    milliseconds=round(frame*1000/fps)
    seconds,ms=divmod(milliseconds,1000)
    minutes,s=divmod(seconds,60);h,m=divmod(minutes,60)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'

def subtitles(layout):
    cues=[]
    for row,seg in zip(layout['project']['clips'],layout['segments']):
        if row['type']=='choice':continue
        if row['type']=='eyecatch':
            pages=[[row['captionText']]] if row['captionEnabled'] and row['captionText'].strip() else []
            spans=[(0,seg['frames'])]
        else:pages=seg['pages'];spans=seg['pageFrames']
        for page,(start,end) in zip(pages,spans):
            text='\n'.join(page).strip()
            if not text:continue
            cues.append(f'{len(cues)+1}\n{timestamp(seg["startFrame"]+start)} --> {timestamp(seg["startFrame"]+end)}\n{text}\n')
    return '\n'.join(cues)
