-- fuente <mailId> <cuenta> : devuelve el MIME crudo del mensaje (para rescatar adjuntos)
on run argv
  set {mailIdStr, cuenta} to argv
  tell application "Mail"
    set m to first message of mailbox "INBOX" of account cuenta whose id is (mailIdStr as integer)
    return source of m
  end tell
end run
