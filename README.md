# orwell - monitoring your tmux output
The goal of the tool is to keep *all* your commands output within a tmux session. I wrote this because I always forgot to save my precious commands output.

[![asciicast](https://asciinema.org/a/8mDdhgIxRM81LGUgFTliCkyvJ.svg)](https://asciinema.org/a/8mDdhgIxRM81LGUgFTliCkyvJ)

You will need tmux (*obviously*) and zsh. As usual :

```bash
git clone https://github.com/0x$USER/orwell
pip install --user -r requirements.txt
```

You will need to run the server :
```
python orwell.py server
```

or with systemd with a user daemon

```
[Unit]
Description=orwerll

[Service]
Type=simple
ExecStart=/path/to/orwerll.py server
Restart=always
RestartSec=5s

[Install]
WantedBy=default.target
```

Then add the following to your `.zshrc`.

```zsh
if { [ -n "$TMUX" ]; } then
	tmux pipe-pane 'exec cat - | python -u /path/to/orwell/orwell.py client $(tmux display-message -p "#S #I #P #{pane_pid}") >> /tmp/orwell-client-debug 2>&1'
fi

preexec() { 
	if { [ -n "$TMUX" ];  } then 

		if [ -S /tmp/logger.sock ]
		then
			pid=$(cat $(tmux display-message -p '/tmp/#S-#I-#P'))
			echo "real cmd : $1" > /proc/$pid/fd/0
		fi
	fi
}

precmd() {
	if { [ -n "$TMUX" ]; } then
		if [ -S /tmp/logger.sock ]
		then
			pane=$(tmux display-message -p '/tmp/#S-#I-#P')
			pid=$(cat $pane)
			echo "::end_cmd::" > /proc/$pid/fd/0
			export LOGGED=TRUE
		else
			export LOGGED=FALSE
		fi
	fi
}
```

And you should be ready. 

All the commands output will be stored in `/home/$USER/.logged/$tmux_session_name/cmd-sha1.log`.


You can also add a fzf binding to list your command wih a simple keyboard shortcut (here ctrl+j). Warning shitty code.

```bash
list() {
	tmux_session=$(tmux display-message -p '#S')
	selected=`cat /home/$USER/.logged/$tmux_session/index | fzf --tac --no-sort --preview 'echo /home/$USER/.logged/$(tmux display-message -p "#S")/$(echo -ne {} | sha1sum | head -c 40).log;cat /home/$USER/.logged/$(tmux display-message -p "#S")/$(echo -ne {} | sha1sum | head -c 40).log' --bind 'enter:execute(echo -ne /home/$USER/.logged/$(tmux display-message -p "#S")/;echo -ne {} | sha1sum | head -c 40; echo .log)+abort'`
	cat $selected
	print -s "cat $selected" >> $HISTFILE
}

clear_list() {
	echo "" > /home/$USER/.logged/$(tmux display-message -p '#S')/index
}

zle -N list
bindkey '^j' list
```