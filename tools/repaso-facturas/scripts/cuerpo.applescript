-- cuerpo <mailId> <cuenta> : devuelve el texto del mensaje
on run argv
  set {mailIdStr, cuenta} to argv
  tell application "Mail"
    set m to first message of mailbox "INBOX" of account cuenta whose id is (mailIdStr as integer)
    return content of m
  end tell
end run
