"""User-controlled character visibility, independent of chat and voice.

C05 (16 Kasım, kullanıcı kararı): "Modeli gizle" = modelsiz çalışma. Gizliyken
VRM bırakılır/yüklenmez ve modele bağlı davranışlar kapanır (arayuz/modelsiz.py);
"Modeli göster" seçili modeli yeniden yükler.
"""
import time

IPUCU='Yumi sesle çalışmaya devam eder; gizliyken model yüklenmez (modelsiz çalışma).'

def visible(owner):return bool(owner.settings.get('model_visible',True))

def apply(owner):
    from modelsiz import gecis,acik,model_yok,MODEL_YOK_YAZISI
    shown=not acik(owner);game=bool(getattr(getattr(owner,'fullscreen_pause',None),'paused',False))
    gecis(owner)
    yok=model_yok(owner)
    # The current shell intentionally keeps its master AvatarView offscreen.
    # It is a state source, not a second character in the 31px status strip.
    owner.avatar.setVisible(shown and not hasattr(owner,'navigation'))
    button=getattr(owner,'model_visibility_button',None)
    if button:
        button.setEnabled(not yok)
        if yok:button.setToolTip(MODEL_YOK_YAZISI+' · '+IPUCU)
        elif button.property('iconOnly'):  # ARAYUZ: başlıkta göz simgesi
            button.setText('');button.setToolTip(('Modeli gizle' if shown else 'Modeli göster')+' · '+IPUCU)
            if hasattr(owner,'_refresh_icons'):owner._refresh_icons()
        else:
            button.setText('Modeli gizle' if shown else 'Modeli göster')
            button.setToolTip(IPUCU)
    for view in (owner.avatar,owner.overlay.avatar):view.set_render_paused(not shown or game)
    owner.overlay.setVisible(shown and not game)
    owner.roam_clock=time.perf_counter();owner.last_render_movement=0.
    if not shown:owner.move_animation.stop()

def set_visible(owner,value):
    from modelsiz import model_yok
    if model_yok(owner):return  # C05: kurulu model yokken gösterilecek bir şey yok
    old=owner.settings.get('model_visible',True);owner.settings['model_visible']=bool(value)
    try:
        from app import save_settings
        save_settings(owner.settings)
    except OSError:
        owner.settings['model_visible']=old
        owner.show_error('Model görünürlüğü kaydedilemedi.');return
    apply(owner)

def add_action(menu,owner):
    action=menu.addAction('');action.setToolTip(IPUCU)
    def refresh():
        from modelsiz import model_yok,MODEL_YOK_YAZISI
        yok=model_yok(owner);action.setEnabled(not yok)
        action.setText(('Modeli göster · '+MODEL_YOK_YAZISI.lower()) if yok else 'Modeli gizle' if visible(owner) else 'Modeli göster')
    refresh();menu.aboutToShow.connect(refresh)
    action.triggered.connect(lambda checked=False:set_visible(owner,not visible(owner)))
    return action
