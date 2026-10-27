# Lab 4: Deploy, watch and pay for it (30 min)

**Book:** Chapter 6 (API-first deployment), Chapter 7 (observability), Chapter 9 (A/B and shadow testing, scaling)
**Industry anchor:** DPD chatbot after an update, 2024

## Setup

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp env.example .env                                     # paste your OpenAI key
```

## Steps

You need **two terminal windows**, both in this folder with the virtual environment activated.

1. **Deploy the bot as a web service (terminal 1):** `python3 monitor.py serve`
   Leave it running. The bot is now an API, like the one a bank's mobile app would call.
2. **Try it by hand in the browser:** open http://localhost:8000/docs, click **POST /v1/ask** →
   **Try it out**, and send `{"question": "How much does the Premium plan cost per month?"}`.
   Then send a message with personal data:
   `{"question": "My card 8600 1234 5678 9012 was declined, what is my daily transfer limit?"}`
   Each answer comes with a `trace_id`: the receipt for that request.
3. **Send real-looking traffic (terminal 2):** `python3 monitor.py load --n 40`
   40 customer messages, including an attack, off-topic questions and personal data.
4. **Watch the dashboard:** open http://localhost:8000/dashboard (refreshes every 5 seconds).
   Requests, speed, tokens, cost per 1,000 requests, blocked attacks, thumbs-down rate.
5. **Investigate:** `python3 monitor.py report` lists the slowest requests and the weakest search
   results. Copy one trace ID and run `python3 monitor.py inspect <trace_id>`: a timeline of that
   one request. Was the card number from step 2 stored, or `[CARD]`?
6. **Shadow test a new version (the DPD lesson):** `python3 shadow.py`
   Marketing wants a "fun" voice (`prompts/v2_fun.txt`). The new prompt answers copies of the real
   questions in secret; customers never see it. Ship or hold? Read the failing example.
7. **Cost of each strategy:** put current prices from https://openai.com/api/pricing into
   `prices.yaml`, then `python3 cost.py compare --eval`. Which strategy is cheapest without losing
   correctness?
8. **Pay per use or run your own?** `python3 cost.py breakeven`, then try `--gpu 900` (a pricier
   GPU). At how many requests a month does running your own model become cheaper?

Stop the API with Ctrl+C in terminal 1 when you are done.

**Key message:** after launch, watch every request, test new versions in the shadows before
customers see them, and know what each answer costs.

## You leave with

A ship-or-hold decision backed by numbers, and a one-sentence cost recommendation.

**Costs:** a full lab with gpt-4o-mini and a few gpt-4o calls costs a few cents per student.
