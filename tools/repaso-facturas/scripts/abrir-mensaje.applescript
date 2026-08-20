-- abrir-mensaje <mailId> <cuenta> : abre el mensaje en Mail (para adjuntos irrescatables)
on run argv
  set {mailIdStr, cuenta} to argv
  tell application "Mail"
    set m to first message of mailbox "INBOX" of account cuenta whose id is (mailIdStr as integer)
    open m
    activate
  end tell
  return "OK"
end run
