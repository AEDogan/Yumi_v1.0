"""Explicit avatar actions block automatic decisions until they complete."""
def manual_action_active(owner,now):
    if getattr(owner,'pending_avatar_command',None) or getattr(owner,'pending_motion_path',None):return True
    if getattr(owner,'voice_target',None) is not None:return True
    if now<getattr(owner,'gesture_until',0.):return True
    runtime=getattr(owner,'music_runtime',None)
    return (getattr(owner,'manual_pose',None) in ('wave','clip','listen')
            and now<getattr(owner,'manual_pose_end',0.) and not getattr(runtime,'active',False))

def is_avatar_command(text):
    from action_transition import ACTIONS,STOP
    from daily_scenarios import SCENARIOS
    text=text.lower().strip(' !?.')
    return text in ACTIONS or text in STOP or text in SCENARIOS or text in {
        'gizlen','saklan','görün','geri gel','büyü','küçül','biraz büyü','biraz küçül',
        'direk dansı yap','pole dance yap','ritme göre dans et','ritimle dans et','müzikle dans et'} or text.startswith('karakter:')
