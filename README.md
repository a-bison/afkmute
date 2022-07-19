# afkmute
A discord bot for server muting AFK people.

## Usage
Use `/afkmute <USER>` to mute someone. This will server mute them, and mark them as "afk-muted". An
afk-muted user may unmute themselves through the `/unafkmute` command. They will also lose afk-muted status
if they take an action that means they can't be AFK (sending a message, muting/deafening themselves, etc.).

`/afkmute` may only be used by users with permission to server mute others. Note that manually removing the
server mute from someone with afk-mute status will remove afk-mute status in the bot as well.
