@staticmethod
async def process_text(supabase_admin, supabase, chat_id, user_id, text, category_pull_service):
    try:
        current_dt = datetime.now(TZ_IST)
        dynamic_system_prompt = SYSTEM_PROMPT.replace("{CURRENT_DATE}",
                                                      f"{current_dt.strftime('%Y-%m-%d')} ({current_dt.strftime('%A')})")

        raw_response_text = execute_resilient_ai(system_prompt=dynamic_system_prompt, user_prompt=text,
                                                 db_client=supabase_admin, is_json=True)
        raw_json = json.loads(raw_response_text)
        validated_data = AITransactionExtraction(**raw_json)
        transactions_list = validated_data.transactions or []

        acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).execute()
        user_accounts = acc_res.data or []

        if not user_accounts and transactions_list:
            await send_telegram_reply(chat_id,
                                      "❌ *No Bank Accounts Configured*\nUse `/addaccount [BankName] [Balance]`")
            return

        if not transactions_list:
            await send_telegram_reply(chat_id, "⚠️ No valid financial transactions were extracted.")
            return

        cache_manager = CategoryCacheManager(supabase, user_id)

        # ================= BULK TRANSACTION PIPELINE =================
        if len(transactions_list) > 1:
            default_acc = AccountHandler.get_account_from_list(user_accounts)
            bulk_service = BulkTransactionService(supabase_admin, user_id, cache_manager, category_pull_service)
            result = bulk_service.process_bulk_payload(transactions_list, default_acc)

            if result["unique"]:
                current_bal = float(default_acc['balance'])
                total_deduction = sum(
                    p["amount"] for p in result["unique"] if p["source_account"] == default_acc['account_name'])
                total_addition = sum(
                    p["amount"] for p in result["unique"] if p["destination_account"] == default_acc['account_name'])

                if (current_bal - total_deduction + total_addition) < 0:
                    await send_telegram_reply(chat_id, f"❌ *Insufficient Balance*")
                    return

                bulk_service.dao.execute_bulk_commit(default_acc['id'], result["unique"], total_deduction,
                                                     total_addition, current_bal)

                bd_text = "\n".join(result["breakdown"]) if result["breakdown"] else "No unique items."

                # DYNAMIC RECEIPT GENERATION
                receipt = (
                    f"🧾 *BULK TRANSACTION SAVED*\n"
                    f"🔴 *EXPENSE* | 🟢 *INCOME* | 🔵 *TRANSFER*\n\n"
                    f"🔹 *Expenses:* ₹{result['totals']['expenses']:,.2f} ({result['counts']['expenses']} items)\n"
                    f"🔹 *Income:* ₹{result['totals']['income']:,.2f} ({result['counts']['income']} items)\n"
                    f"🔹 *Transfers:* ₹{result['totals']['transfers']:,.2f} ({result['counts']['transfers']} items)\n\n"
                    f"🔹 *Primary Account:* {default_acc['account_name']}\n"
                    f"🛒 *Receipt Breakdown:*\n{bd_text}"
                )

                if result["ignored"]:
                    receipt += f"\n\n🚫 *Ignored Items:*\n" + "\n".join(result["ignored"])

                await send_telegram_reply(chat_id, receipt)

            if result["duplicates"]:
                batch_id = uuid.uuid4().hex[:8]
                PENDING_BATCHES[batch_id] = {"user_id": user_id, "account_id": default_acc['id'],
                                             "items": result["duplicates"]}
                keyboard = CallbackHandler.generate_duplicate_keyboard(batch_id, result["duplicates"])
                await send_telegram_reply(chat_id,
                                          f"⚠️ *Duplicate Entries Found ({len(result['duplicates'])} items)*\nTap to select/save duplicates.",
                                          reply_markup=keyboard)
            return

        # ================= SINGLE TRANSACTION PIPELINE =================
        response_sections, committed_items = [], []
        for tx in transactions_list:
            amount = tx.amount if tx.amount else Decimal('0.00')
            description = str(tx.item or tx.merchant or text).title()

            if amount > Decimal('0.00'):
                if tx.future and tx.future.is_future:
                    response_sections.append(f"🗓️ '{description}' identified as future plan.")
                    continue
                if not tx.intent or tx.needs_clarification:
                    response_sections.append(
                        f"⚠️ Could not process '{description}'. Clarify: {','.join(tx.clarification_fields or [])}")
                    continue

                tx_dates = []
                is_recurring_past = False
                if tx.recurrence and tx.recurrence.enabled and tx.recurrence.start_date:
                    tx_dates = generate_recurrence_dates(tx.recurrence.start_date, tx.recurrence.frequency or "monthly",
                                                         current_dt)
                    if tx_dates: is_recurring_past = True
                if not is_recurring_past:
                    db_date_obj = current_dt
                    if tx.date and tx.date.relative_date:
                        try:
                            db_date_obj = datetime.strptime(tx.date.relative_date.split("T")[0], "%Y-%m-%d").replace(
                                tzinfo=TZ_IST)
                        except:
                            pass
                    tx_dates = [db_date_obj]

                num_occ = Decimal(len(tx_dates))
                tot_amt = amount * num_occ
                source_acc_obj = AccountHandler.get_account_from_list(user_accounts,
                                                                      tx.source_account) if tx.intent in ["expense",
                                                                                                          "transfer_other",
                                                                                                          "transfer_own"] else None
                dest_acc_obj = AccountHandler.get_account_from_list(user_accounts,
                                                                    tx.destination_account) if tx.intent in ["income",
                                                                                                             "transfer_own"] else None

                updates_to_make = []
                if tot_amt > Decimal('0.00'):
                    if source_acc_obj:
                        current_bal = Decimal(str(source_acc_obj['balance']))
                        if current_bal < tot_amt:
                            response_sections.append(f"❌ *Insufficient Balance* in {source_acc_obj['account_name']}.")
                            continue
                        updates_to_make.append(
                            (source_acc_obj['id'], float(current_bal - tot_amt), "DEBIT", float(tot_amt)))
                    if dest_acc_obj:
                        updates_to_make.append(
                            (dest_acc_obj['id'], float(Decimal(str(dest_acc_obj['balance'])) + tot_amt), "CREDIT",
                             float(tot_amt)))

                for acc_id, new_bal, log_type, txn_amount in updates_to_make:
                    supabase_admin.table('accounts').update({"balance": new_bal}).eq("id", acc_id).execute()
                    try:
                        supabase_admin.table('account_logs').insert(
                            {"account_id": acc_id, "user_id": user_id, "log_type": log_type, "amount": txn_amount,
                             "balance_after": new_bal, "description": description}).execute()
                    except:
                        pass

                category = tx.category
                subcategory = tx.subcategory
                if not category:
                    cached = cache_manager.search_item(description)
                    if cached and cached.get("category"):
                        category, subcategory = cached["category"], cached.get("subcategory")
                    else:
                        ai_cls = category_pull_service.classify_item(description, intent=tx.intent)
                        category, subcategory = ai_cls.get("category", "General"), ai_cls.get("subcategory",
                                                                                              "Miscellaneous")

                db_payloads = [
                    {"user_id": user_id, "amount": float(amount), "txn_type": tx.intent, "description": description,
                     "intent": tx.intent, "category": category, "subcategory": subcategory, "date": d.isoformat(),
                     "source_account": source_acc_obj['account_name'] if source_acc_obj else None,
                     "destination_account": dest_acc_obj['account_name'] if dest_acc_obj else None,
                     "soft_deleted": False} for d in tx_dates]

                try:
                    if len(db_payloads) == 1:
                        supabase.table("transactions").insert(db_payloads[0]).execute()
                    elif len(db_payloads) > 1:
                        supabase.table("transactions").insert(db_payloads).execute()
                except:
                    continue

                committed_items.append(f"✅ *Transaction Saved*\n🔹 {description}: ₹{float(amount):,.2f}")

        if committed_items: response_sections.append("\n\n".join(committed_items))
        if response_sections: await send_telegram_reply(chat_id, "\n\n".join(response_sections))
    except Exception as e:
        await send_telegram_reply(chat_id, f"Error processing text: {str(e)}")