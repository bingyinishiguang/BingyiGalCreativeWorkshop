"""Explicit ordered visuals, compiled into the existing single background track."""
import math
import uuid


def normalize_sequence(raw):
    from rough_cut import number
    if not isinstance(raw,list) or len(raw)>500:raise ValueError('顺序画面最多500项')
    rows=[];seen=set()
    for index,row in enumerate(raw):
        if not isinstance(row,dict):raise ValueError('顺序画面格式不正确')
        from column_workflow import ColumnWorkflow
        item_id=ColumnWorkflow.key(row.get('itemId') or uuid.uuid4().hex)
        if item_id in seen:raise ValueError('顺序画面编号重复')
        seen.add(item_id)
        mode=row.get('timing','fixed')
        if mode not in ('fixed','remainder'):raise ValueError('顺序画面时长方式不支持')
        if mode=='remainder' and index!=len(raw)-1:raise ValueError('填满剩余的图片只能放在最后')
        limit=row.get('maxDuration')
        rows.append({'itemId':item_id,'background':str(row.get('background') or ''),'timing':mode,
                     'sourceStart':number(row.get('sourceStart',0),'视频起点',0,86400),
                     'gapBefore':number(row.get('gapBefore',0),'前方空隙',0,10800),
                     'duration':number(row.get('duration',5),'取用或停留时长',1/60,3600),
                     'maxDuration':None if limit in (None,'') else number(limit,'补图最长时长',1/60,10800),
                     'acceptFrameAdjustment':row.get('acceptFrameAdjustment') is True})
    return rows


def compile_sequence(rows,backgrounds,fps,start_frame,end_frame):
    if not rows:raise ValueError('请添加顺序画面')
    scenes=[];resolved=[];cursor=start_frame
    for row in rows:
        label='顺序画面 '+str(len(resolved)+1)
        info=backgrounds.get(row['background']);backgrounds.file(row['background'])
        gap_start=cursor
        gap=round(row.get('gapBefore',0)*fps)
        if abs(gap/fps-row.get('gapBefore',0))>1e-8 and not row['acceptFrameAdjustment']:
            raise ValueError(label+'：前方空隙需确认按帧对齐')
        if end_frame is not None and cursor+gap>end_frame:raise ValueError('空隙超出配音时长')
        while gap:
            amount=min(gap,3600*fps)
            scenes.append({'id':uuid.uuid4().hex,'sourceRow':row['itemId'],'blank':True,'background':'','duration':amount/fps,'actors':[]})
            cursor+=amount;gap-=amount
        gap_end=cursor
        source_us=round(row['sourceStart']*1e6) if info['kind']=='video' else 0
        requested=row['duration']
        if row['timing']=='remainder':
            if info['kind']!='image':raise ValueError(label+'：填满剩余只支持图片')
            frames=0 if end_frame is None else end_frame-cursor
            if frames<0:raise ValueError(f'固定画面超出配音 {(-frames)/fps:.3f} 秒，请调整取用范围')
            if row['maxDuration'] is not None and frames/fps>row['maxDuration']+1e-8:
                raise ValueError(f"补图达到上限后仍缺 {frames/fps-row['maxDuration']:.3f} 秒，请补充画面")
        else:
            exact=requested*fps
            frames=math.floor(exact+1e-8) if info['kind']=='video' else round(exact)
            if frames<1:raise ValueError(label+'：不足一个输出帧，请调整时长')
            if info['kind']=='video':
                if source_us+round(requested*1e6)>round(info['duration']*1e6):raise ValueError(label+'：取用区间超过视频结尾，请调整起点或时长')
                while frames and round((cursor+frames)*1e6/fps)-round(cursor*1e6/fps)>round(requested*1e6):frames-=1
            if frames<1:raise ValueError(label+'：没有可用的完整输出帧')
            if abs(frames/fps-requested)>1e-8 and not row['acceptFrameAdjustment']:
                raise ValueError(f'{label}：{requested:.6f} 秒会对齐为 {frames/fps:.6f} 秒，请确认按帧对齐或调整时长')
            if end_frame is not None and cursor+frames>end_frame:raise ValueError(f'固定画面超出配音 {(cursor+frames-end_frame)/fps:.3f} 秒，请调整取用范围')
        begin=cursor
        remaining=frames;offset_us=0
        while remaining:
            amount=min(remaining,3600*fps)
            duration_us=round((cursor+amount)*1e6/fps)-round(cursor*1e6/fps)
            scenes.append({'id':uuid.uuid4().hex,'sourceRow':row['itemId'],'background':row['background'],
                           'duration':amount/fps,'videoStart':(source_us+offset_us)/1e6,'restart':True,'loop':False,'actors':[]})
            cursor+=amount;remaining-=amount;offset_us+=duration_us
        resolved.append({'itemId':row['itemId'],'asset':row['background'],'requestedDuration':requested if row['timing']=='fixed' else None,
                         'sourceStartUs':source_us,'startFrame':begin,'endFrame':cursor,'durationUs':round(cursor*1e6/fps)-round(begin*1e6/fps),
                         'gapStartFrame':gap_start,'gapEndFrame':gap_end,
                         'clipIds':[s['id'] for s in scenes if s['sourceRow']==row['itemId'] and not s.get('blank')]})
    if end_frame is not None and cursor<end_frame:raise ValueError(f'顺序画面还差 {(end_frame-cursor)/fps:.3f} 秒，请添加图片并明确选择填满剩余')
    if len(scenes)>500:raise ValueError('顺序画面超过500个输出镜头')
    return scenes,resolved
