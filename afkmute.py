import asyncio
import dataclasses
import logging
from dataclasses import dataclass
import dotenv
import hikari
import lightbulb
import os
from pathlib import Path
import typing as t
import saru

logger = logging.getLogger(__name__)

dotenv.load_dotenv()


def get_token() -> str:
    return os.environ["BOT_TOKEN"]


def generate_invite(bot: hikari.GatewayBot) -> str:
    return f"https://discord.com/api/oauth2/authorize?client_id={bot.get_me().id}&permissions=4194304&scope=bot%20applications.commands"


@dataclass
class AfkMuteInfo:
    user_id: int
    muter_id: int

    def as_dict(self) -> t.MutableMapping[str, saru.ConfigValue]:
        return dataclasses.asdict(self)


@saru.config_backed("g/afk_mute_users")
class AfkMuteState(saru.GuildStateBase):
    def is_afk_mute(self, user: hikari.Member) -> bool:
        return str(user.id) in self.cfg

    def is_user_in_vc(self, user: hikari.Member) -> bool:
        return self.guild.get_voice_state(user) is not None

    async def set_afk_mute(self, user: hikari.Member, muter: hikari.Member) -> AfkMuteInfo:
        if self.is_afk_mute(user):
            raise UserAlreadyAfkMuteError()

        if self.is_user_in_vc(user):
            await user.edit(mute=True)

        i = AfkMuteInfo(
            user_id=user.id,
            muter_id=muter.id
        )
        self.cfg.set(str(user.id), i.as_dict())

        return i

    async def unset_afk_mute(self, user: hikari.Member, no_vc_ok: bool = False) -> None:
        if not self.is_afk_mute(user):
            raise UserNotAfkMuteError()

        if not no_vc_ok and not self.is_user_in_vc(user):
            raise UserNotInVcError()

        if not no_vc_ok:
            await user.edit(mute=False)

        self.cfg.delete(str(user.id))

    async def fetch_afk_mute_state(self, app: hikari.RESTAware) -> None:
        info_items = [AfkMuteInfo(**value) for value in self.cfg.opts.values()]

        for info in info_items:
            member = await app.rest.fetch_member(self.guild.id, info.user_id)
            voice_state = self.guild.get_voice_state(member.id)

            if voice_state is not None and not voice_state.is_guild_muted:
                await self.unset_afk_mute(member, no_vc_ok=True)


intents = (
    hikari.Intents.GUILDS |
    hikari.Intents.GUILD_MESSAGES |
    hikari.Intents.GUILD_MESSAGE_REACTIONS |
    hikari.Intents.GUILD_VOICE_STATES
)
bot = lightbulb.BotApp(get_token(), intents=intents)
saru.attach(bot, config_path=Path("cfg"))
saru.get(bot).gstype(AfkMuteState)


class AfkMuteError(Exception):
    pass


class UserAlreadyAfkMuteError(AfkMuteError):
    pass


class UserNotAfkMuteError(AfkMuteError):
    pass


class UserNotInVcError(AfkMuteError):
    pass


def err_embed(error_text: str) -> hikari.Embed:
    embed = hikari.Embed(title="Error", color=hikari.Color.from_rgb(255, 0, 0), description=error_text)
    return embed


def success_embed(desc: str) -> hikari.Embed:
    embed = hikari.Embed(title="Success", color=hikari.Color.from_rgb(0, 255, 0), description=desc)
    return embed


@bot.command()
@lightbulb.set_help(
    "Generate an invite link for this bot."
)
@lightbulb.command(
    "invite",
    "Create an invite for AfkMute."
)
@lightbulb.implements(lightbulb.SlashCommand)
async def invite(ctx: lightbulb.Context) -> None:
    await ctx.respond(hikari.Embed(title="Click here to invite.", url=generate_invite(ctx.bot)))


@bot.command()
@lightbulb.set_help(
    "AFK mutes someone. Only those who have permission to mute people can use this command, but the user may "
    "un-mute themselves through the /unafkmute command."
)
@lightbulb.option(
    "user",
    "The user to mute.",
    type=hikari.Member
)
@lightbulb.app_command_permissions(
    hikari.Permissions.MUTE_MEMBERS,
    dm_enabled=False
)
@lightbulb.command(
    "afkmute",
    "AFK mute someone."
)
@lightbulb.implements(lightbulb.SlashCommand)
async def afkmute(ctx: lightbulb.Context) -> None:
    target: hikari.Member = ctx.options.user

    try:
        state = await AfkMuteState.get(ctx)
        await state.set_afk_mute(target, ctx.member)
    except UserAlreadyAfkMuteError:
        await ctx.respond(err_embed("This user is already afk-muted."), flags=hikari.MessageFlag.EPHEMERAL)
        return

    msg = (
        f"{target.mention}, you have been afk-muted. You can unmute yourself by running `/unafkmute`, or by doing "
        "something (sending a message, self-muting/deafening, reacting to a message, etc).\n\n"
        "Remember to mute yourself next time."
    )

    await ctx.respond(msg, user_mentions=True)


@bot.command()
@lightbulb.set_help(
    "Unmute yourself if you were afk-muted."
)
@lightbulb.command(
    "unafkmute",
    "Remove AFK mute status from yourself."
)
@lightbulb.implements(lightbulb.SlashCommand)
async def unafkmute(ctx: lightbulb.Context) -> None:
    try:
        state = await AfkMuteState.get(ctx)
        await state.unset_afk_mute(ctx.member)
    except UserNotAfkMuteError:
        await ctx.respond(err_embed("You are not afk-muted."), flags=hikari.MessageFlag.EPHEMERAL)
        return
    except UserNotInVcError:
        await ctx.respond(err_embed("You must be in vc to remove afk-mute status."), flags=hikari.MessageFlag.EPHEMERAL)
        return

    await ctx.respond(success_embed("You have been unmuted."), flags=hikari.MessageFlag.EPHEMERAL)


@bot.listen(hikari.VoiceStateUpdateEvent)
async def on_voice_state_update(event: hikari.VoiceStateUpdateEvent) -> None:
    state: AfkMuteState = await saru.get(bot).gs(AfkMuteState, event.guild_id)

    # If a user marked as afk-mute is unmuted manually, make sure to remove the cfg entry.
    manually_unmuted = (
        event.old_state is not None and
        event.old_state.is_guild_muted and
        not event.state.is_guild_muted
    )
    if manually_unmuted and state.is_afk_mute(event.state.member):
        await state.unset_afk_mute(event.state.member)
        return

    # Next, check if the user just joined voice. If so, update their voice state to be in line with
    # the afk-mute.
    joined_vc = (
        event.old_state is None and
        event.state.channel_id is not None
    )
    if joined_vc and state.is_afk_mute(event.state.member) and not event.state.is_guild_muted:
        await event.state.member.edit(mute=True)

    # However, for the opposite, not afk-muted but server muted, we should *not* update the state. They could have
    # been forcibly muted external to our application.

    # If nothing to compare to, don't bother.
    if event.old_state is None:
        return

    # Otherwise, check for some status changes that can only be invoked by the user. If any have occurred,
    # unmute the user.
    # Unfortunately, channel_id doesn't count, because it can be changed by an administrator, and there's
    # no reliable way to tell *who* changed the channel ID.
    user_status = [
        "is_self_deafened",
        "is_self_muted",
        "is_streaming",
        "is_video_enabled"
    ]
    for status in user_status:
        prev: bool = getattr(event.old_state, status)
        cur: bool = getattr(event.state, status)

        if prev != cur:
            await state.unset_afk_mute(event.state.member)
            return


@bot.listen(
    hikari.GuildMessageCreateEvent,
    hikari.GuildMessageUpdateEvent,
    hikari.GuildReactionEvent
)
async def on_member_message_action(
    event: t.Union[
        hikari.GuildMessageCreateEvent,
        hikari.GuildMessageUpdateEvent,
        hikari.GuildReactionEvent
    ]
) -> None:
    # Unmute on message updates. Delete is not included because it can be invoked by some other user.
    state: AfkMuteState = await saru.get(bot).gs(AfkMuteState, event.guild_id)

    if isinstance(event, hikari.GuildReactionEvent):
        member = bot.cache.get_member(event.guild_id, event.user_id)
    else:
        member = event.member

    if state.is_afk_mute(member):
        try:
            await state.unset_afk_mute(member)
        except UserNotInVcError:
            pass


@bot.listen(hikari.StartedEvent)
async def on_started(event: hikari.StartedEvent) -> None:
    s = saru.get(bot)

    for _ in range(10):
        await asyncio.sleep(1)
        if s.is_ready:
            logger.info("Saru ready, updating mute state.")
            break
    else:
        logger.error("Saru not ready in 10 secs, considering this failure.")
        return

    for guild in (await bot.rest.fetch_my_guilds()):
        gs: AfkMuteState = await s.gs(AfkMuteState, guild.id)
        await gs.fetch_afk_mute_state(event.app)


bot.run()
