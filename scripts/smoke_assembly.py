from __future__ import annotations

import compileall
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bot_async


def assemble_application() -> int:
    app = bot_async.build_application("123:TEST", bot_async.post_init, bot_async._on_shutdown)
    app.bot_data["build_usage_audit_keyboard"] = bot_async.build_usage_audit_keyboard
    bot_async.register_handlers(
        app,
        {
            "start": bot_async.start_command,
            "help": bot_async.help_command,
            "check": bot_async.check_command,
            "checkall": bot_async.checkall_command,
            "allowall": bot_async.allowall_command,
            "denyall": bot_async.denyall_command,
            "list": bot_async.list_command,
            "stats": bot_async.stats_command,
            "export": bot_async.export_command,
            "import": bot_async.import_command,
            "adduser": bot_async.add_user_command,
            "deluser": bot_async.del_user_command,
            "listusers": bot_async.list_users_command,
            "usageaudit": bot_async.usageaudit_command,
            "globallist": bot_async.globallist_command,
            "broadcast": bot_async.broadcast_command,
            "to_yaml": bot_async.to_yaml_command,
            "to_txt": bot_async.to_txt_command,
            "deepcheck": bot_async.deepcheck_command,
            "delete": bot_async.delete_command,
            "refresh_menu": bot_async.refresh_menu_command,
            "backup": bot_async.backup_command,
            "restore": bot_async.restore_command,
            "button_callback": bot_async.button_callback,
            "handle_document": bot_async.handle_document,
            "handle_message": bot_async.handle_message,
        },
    )
    return sum(len(group) for group in app.handlers.values())


def main() -> None:
    print("compileall", compileall.compile_dir(".", quiet=1))
    print("handlers registered", assemble_application())


if __name__ == "__main__":
    main()
