-- etiquetar <mailId> <etiqueta> <cuenta> <messageId> : añade la etiqueta Gmail.
-- Verifica el Message-ID antes de tocar nada: si Mail reasignó el id numérico,
-- devuelve MISMATCH y no etiqueta el correo equivocado.
on run argv
  set {mailIdStr, etiqueta, cuenta, mid} to argv
  tell application "Mail"
    set cta to account cuenta
    if not (exists mailbox etiqueta of cta) then
      make new mailbox with properties {name:etiqueta} at cta
    end if
    set m to first message of mailbox "INBOX" of cta whose id is (mailIdStr as integer)
    if mid is not "" then
      if (message id of m) is not equal to mid then error "MISMATCH: el id apunta a otro mensaje"
    end if
    duplicate m to mailbox etiqueta of cta
  end tell
  return "OK"
end run
