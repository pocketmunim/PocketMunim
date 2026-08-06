from app.telegram.telegram_utils import send_telegram_reply


class AccountHandler:
    @staticmethod
    def get_account_from_list(accounts_list, target_name=None):
        if not accounts_list: return None
        if target_name:
            target_clean = target_name.strip().lower()
            for acc in accounts_list:
                if acc['account_name'].lower() == target_clean:
                    return acc
            return None
        for acc in accounts_list:
            if acc.get('is_default'): return acc
        return accounts_list[0]

    @staticmethod
    async def add_account(supabase_admin, chat_id, user_id, text):
        parts = text.replace("/addaccount", "").strip().split()
        if len(parts) < 2:
            await send_telegram_reply(chat_id, "⚠️ Use: `/addaccount [BankName] [Balance]`")
            return
        acc_name = " ".join(parts[:-1]).title()
        try:
            acc_bal = float(parts[-1])
        except ValueError:
            await send_telegram_reply(chat_id, "⚠️ Invalid balance amount.")
            return

        try:
            existing_accs = supabase_admin.table('accounts').select('id').eq('user_id', user_id).execute()
            is_first = len(existing_accs.data) == 0

            supabase_admin.table('accounts').insert({
                "user_id": user_id, "account_name": acc_name, "balance": acc_bal, "is_default": is_first
            }).execute()
            await send_telegram_reply(chat_id, f"✅ *Account Added*\nName: {acc_name}\nBalance: ₹{acc_bal:,.2f}")
        except Exception as e:
            # 🚀 EXACT ERROR EXPOSURE
            await send_telegram_reply(chat_id, f"⚠️ Failed to add account:\n`{str(e)}`")

    @staticmethod
    async def set_default(supabase_admin, chat_id, user_id, text):
        acc_name = text.replace("/setdefault", "").strip().title()
        if not acc_name:
            await send_telegram_reply(chat_id, "⚠️ Please provide an account name.")
            return

        try:
            acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).ilike('account_name',
                                                                                                acc_name).execute()
            if not acc_res.data:
                await send_telegram_reply(chat_id, f"⚠️ Account '{acc_name}' not found.")
                return

            supabase_admin.table('accounts').update({"is_default": False}).eq('user_id', user_id).execute()
            supabase_admin.table('accounts').update({"is_default": True}).eq('id', acc_res.data[0]['id']).execute()
            await send_telegram_reply(chat_id, f"✅ '{acc_res.data[0]['account_name']}' is now your default account.")
        except Exception as e:
            # 🚀 EXACT ERROR EXPOSURE
            await send_telegram_reply(chat_id, f"⚠️ Failed to set default:\n`{str(e)}`")