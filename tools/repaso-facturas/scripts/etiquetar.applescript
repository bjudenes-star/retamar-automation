-- etiquetar <mailId> <etiqueta> <cuenta> : añade la etiqueta Gmail (duplicate = añadir, NO saca de INBOX)
on run argv
  set {mailIdStr, etiqueta, cuenta} to argv
  tell application "Mail"
    set cta to account cuenta
    if not (exists mailbox etiqueta of cta) then
      make new mailbox with properties {name:etiqueta} at cta
    end if
    set m to first message of mailbox "INBOX" of cta whose id is (mailIdStr as integer)
    duplicate m to mailbox etiqueta of cta
  end tell
  return "OK"
end run
