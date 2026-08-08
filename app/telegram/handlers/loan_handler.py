@staticmethod
async def handle_loan_text(supabase_admin, chat_id, user_id, text) -> str:
    extractor = LoanExtractionService(supabase_admin)
    loan_service = LoanService(supabase_admin, user_id)

    try:
        # Now returns a tuple: (actions, leftover_text)
        parsed_actions, leftover_text = await extractor.parse_loan_text(text)
        response_messages = []

        for parsed in parsed_actions:
            if parsed.action == "CREATE":
                msg, success = await loan_service.create_loan(parsed)
                response_messages.append(msg)
            elif parsed.action == "PAY_EMI":
                msg, res_status = await loan_service.process_emi_payment(
                    lender_name=parsed.lender_name,
                    payment_amount=parsed.payment_amount,
                    target_period=parsed.target_period
                )

                if isinstance(res_status, dict) and res_status.get("status") == "NEXT_EMI_CONFIRM":
                    next_sched_id = res_status["next_schedule_id"]
                    loan_id = res_status["loan_id"]
                    keyboard = {
                        "inline_keyboard": [
                            [{"text": "Pay Next Month EMI", "callback_data": f"paynext_{loan_id}_{next_sched_id}"}],
                            [{"text": "Cancel", "callback_data": "cancelpay"}]
                        ]
                    }
                    await send_telegram_reply(chat_id, msg, reply_markup=keyboard)
                else:
                    response_messages.append(msg)

        if response_messages:
            await send_telegram_reply(chat_id, "\n\n".join(response_messages))

        # Return the non-loan text so main.py can process it
        return leftover_text
    except Exception as e:
        await send_telegram_reply(chat_id, f"⚠️ Batch Processing Error: {str(e)}")
        return {str(e)}