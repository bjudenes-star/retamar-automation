-- guardar-adjuntos <mailId> <carpetaDestino> <prefijo> <cuenta> : POR MENSAJE, tolera fallos
on run argv
  set {mailIdStr, destino, prefijo, cuenta} to argv
  set resultado to ""
  tell application "Mail"
    set m to first message of mailbox "INBOX" of account cuenta whose id is (mailIdStr as integer)
    set n to 0
    repeat with adj in mail attachments of m
      set n to n + 1
      try
        if downloaded of adj is false then error "no descargado del servidor"
        set nombre to name of adj
        set rutaFin to destino & "/" & prefijo & "_" & n & "_" & nombre
        save adj in POSIX file rutaFin
        set resultado to resultado & "OK" & tab & nombre & linefeed
      on error msg
        set resultado to resultado & "FALLO" & tab & msg & linefeed
      end try
    end repeat
    if n is 0 then set resultado to "SIN_ADJUNTOS"
  end tell
  return resultado
end run
