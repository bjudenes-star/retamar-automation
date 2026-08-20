-- listar <díasAtrás> <cuenta> : INBOX → TSV id·messageId·remitente·asunto·fecha·nAdj·etiquetas
on run argv
  set diasAtras to (item 1 of argv) as integer
  set cuenta to item 2 of argv
  set corte to (current date) - (diasAtras * days)
  set salida to ""
  tell application "Mail"
    set bandeja to mailbox "INBOX" of account cuenta
    set n to count of messages of bandeja
    set i to 1
    repeat while i <= n
      try
        set m to message i of bandeja
        set fr to date received of m
        if fr < corte then exit repeat
        set numAdj to count of mail attachments of m
        set etiquetas to ""
        try
          repeat with bz in mailboxes of m
            set etiquetas to etiquetas & (name of bz) & ";"
          end repeat
        end try
        set y to year of fr as string
        set mo to text -2 thru -1 of ("0" & ((month of fr as integer) as string))
        set dy to text -2 thru -1 of ("0" & (day of fr as string))
        set asu to subject of m
        set salida to salida & (id of m) & tab & (message id of m) & tab & (sender of m) & tab & asu & tab & y & "-" & mo & "-" & dy & tab & numAdj & tab & etiquetas & linefeed
      on error
        set salida to salida & "ERR" & tab & i & linefeed
      end try
      set i to i + 1
    end repeat
  end tell
  return salida
end run
