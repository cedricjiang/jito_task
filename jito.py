import logging
import time

from argparse import ArgumentParser, Namespace
from collections import defaultdict
from math import prod
from typing import Any
import heapq
import json
import requests

MAIN_NET_BETA_RPC_URL = "https://api.mainnet-beta.solana.com"
HEADERS = {"Content-Type": "application/json"}
BODY_BASE = {"jsonrpc": "2.0", "id": 1}

CSV_HEADER = "signature,beneficiary,mint,amount"

WSOL = "So11111111111111111111111111111111111111112"
KNOWN_TOKEN_VALUE = {
    # hard coding $200 for (wrapped) SOL for simplicity
    WSOL: 200.0,
    # stable coins
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 1.0,
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 1.0,
}


def parse_args() -> Namespace:
    """
    Parse command line args

    :return: parsed arguments
    """
    parser = ArgumentParser()
    parser.add_argument(
        "-b",
        "--begin-slot",
        help="the beginning slot number (inclusive)",
        type=int,
        default=308803801,
    )
    parser.add_argument(
        "-e",
        "--end-slot",
        help="the end slot number (inclusive)",
        type=int,
        default=308803900,
    )
    parser.add_argument(
        "-l", "--log-file", help="the log file path", type=str, default="jito.log"
    )
    parser.add_argument(
        "-d",
        "--data-file",
        help="the data (CSV) file path",
        type=str,
        default="jito.csv",
    )
    parser.add_argument(
        "-t",
        "--top",
        help="the number of top traders in statistics",
        type=int,
        default=10,
    )
    return parser.parse_args()


def rpc(method: str, params: Any) -> Any:
    """
    Make one RPC call with "guaranteed" success and non-guaranteed execution
    time (due to possible retry)

    :param method: the RPC method
    :param params: the RPC parameters
    :return: the RPC response result in JSON
    """
    while True:
        response = requests.post(
            MAIN_NET_BETA_RPC_URL,
            headers=HEADERS,
            json=BODY_BASE | {"method": method, "params": params},
        )

        # finger crossed
        assert response.status_code != 403, "What? permanently banned!"

        if response.status_code == 200:
            return response.json()

        if response.status_code == 429 and "retry-after" in response.headers:
            wait = int(response.headers["retry-after"])
            logging.warning(f"Rate limited and will retry after {wait} seconds")
            time.sleep(wait)

        # more wait, either we don't get the retry instruction or we want to
        # additionally wait for one second for safety margin
        time.sleep(1)


def get_blocks(begin_slot: int, end_slot: int) -> list[int]:
    """
    Run one RPC call to get blocks between begin and end

    :param begin_slot: the beginning slot number, inclusive
    :param end_slot: the end slot number, inclusive
    :return: list of slot numbers between begin and end
    """
    return rpc("getBlocks", [begin_slot, end_slot])["result"]


def get_block_transactions(slot: int) -> list[dict]:
    """
    Run one RPC call to get block data for given slot

    :param slot: slot number, must exist
    :return: transaction data in the block in JSON format
    """
    params = [
        slot,
        {
            "encoding": "json",
            "maxSupportedTransactionVersion": 0,
            "transactionDetails": "accounts",  # sufficient for our approach
            "rewards": False,
        },
    ]
    return rpc("getBlock", params)["result"]["transactions"]


def construct_balance_changes(transaction: dict) -> dict:
    per_owner_per_mint_change = defaultdict(lambda: defaultdict(int))

    # same token should have same decimals, we assume this in the code so we
    # just add to this map without checking if the new value is the same
    # as the old value (if there is one)
    per_mint_decimals = {}

    for post in transaction["meta"]["postTokenBalances"]:
        per_owner_per_mint_change[post["owner"]][post["mint"]] += int(
            post["uiTokenAmount"]["amount"] or "0"
        )
        per_mint_decimals[post["mint"]] = post["uiTokenAmount"]["decimals"]

    for pre in transaction["meta"]["preTokenBalances"]:
        per_owner_per_mint_change[pre["owner"]][pre["mint"]] -= int(
            pre["uiTokenAmount"]["amount"] or "0"
        )
        per_mint_decimals[pre["mint"]] = pre["uiTokenAmount"]["decimals"]

    return {
        k: {x: y / 10 ** per_mint_decimals[x] for x, y in v.items() if y != 0}
        for k, v in per_owner_per_mint_change.items()
        if v
    }


def main():
    args = parse_args()

    logging.basicConfig(filename=args.log_file, filemode="w", level=logging.DEBUG)

    slots = get_blocks(args.begin_slot, args.end_slot)

    logging.info(f"{len(slots)} slots between {args.begin_slot} and {args.end_slot}")

    records = []

    for slot in slots:
        logging.info(f"Analyzing slot {slot}")

        for transaction in get_block_transactions(slot):
            signature = transaction["transaction"]["signatures"][0]
            # consider only the first signer (if multiple) to be potential
            # beneficiary for arbitrage
            signer = transaction["transaction"]["accountKeys"][0]["pubkey"]

            logging.info(f"Analyzing transaction {signature} by {signer}")

            per_owner_per_mint_change = construct_balance_changes(transaction)
            per_owner_per_mint_change.pop(signer, None)

            # map from a tuple of token and amount of change to two accounts
            # (owners) that have this change (outflow and inflow), see writeup
            # for example
            token_change_owners = defaultdict(lambda: [None, None])

            for owner, per_mint_change in per_owner_per_mint_change.items():
                if len(per_mint_change) == 2 and prod(per_mint_change.values()) < 0:
                    for mint, change in per_mint_change.items():
                        token_change_owners[(mint, abs(change))][0 if change < 0 else 1] = owner

            # then consider the owner pair where neither is None, which
            # represents a pair that is likely involved the arbitrage
            pairs = [v for v in token_change_owners.values() if v[0] and v[1]]

            links = []

            # since multiple pairs could be working together for this arbitrage
            # we look for a "chain", by selecting a random (implementation is
            # to take the last) pair and try to look for other pairs that can
            # be used to extend this link from either direction
            while pairs:
                link = pairs.pop()

                while True:
                    found = False

                    # try to find one additional pair to "extend" the link one
                    # at a time
                    for l in pairs:
                        if l[0] == link[-1]:
                            link.append(l[1])
                            pairs.remove(l)
                            found = True
                        elif l[1] == link[0]:
                            # not O(1) fwiw
                            link.insert(0, l[0])
                            pairs.remove(l)
                            found = True

                        if found:
                            break

                    # not found means this link is now longest and cannot be
                    # extended, we record it and break this "while True" loop
                    # so we can process remainder in "pairs"
                    if not found:
                        links.append((link[0], link[-1]))
                        break

            for first, last in links:
                # for the first owner (exchange), look for the token balance
                # increase - this is the amount the signer "paid"
                for first_token, first_value in per_owner_per_mint_change[first].items():
                    if first_value > 0:
                        break

                # for the second owner (exchange), look for the token balance
                # decrease - this is the amount the signer "received"
                for last_token, last_value in per_owner_per_mint_change[last].items():
                    if last_value < 0:
                        break

                # if they are the same token then there is likely an arbitrage
                # we do not do any other checks on signer's balance, see writeup
                # for details
                if first_token == last_token:
                    logging.info(
                        json.dumps(per_owner_per_mint_change, indent=4),
                    )
                    records.append((signature, signer, first_token, -(first_value + last_value)))

    with open(args.data_file, "w") as f:
        biggest = (0, None)
        total_dollar = 0.0
        count = 0
        per_signer_dollar = defaultdict(float)

        print(CSV_HEADER, file=f)

        for signature, signer, token, amount in records:
            print(f"{signature},{signer},{token},{amount}", file=f)

            if token not in KNOWN_TOKEN_VALUE:
                # ignore for now, given they seem rare
                logging.error(f"Saw unknown token {token} in transaction {signature}")
                continue

            curr = amount * KNOWN_TOKEN_VALUE[token]
            if curr > biggest[0]:
                biggest = (
                    curr,
                    f"{signer} made ${curr} in transaction {signature} with {amount} of {token}",
                )
            count += 1
            total_dollar += curr
            per_signer_dollar[signer] += curr

        print(
            f"Total {count} transactions made ${total_dollar}, an average of ${total_dollar / count}"
        )
        print("Biggest transaction:", biggest[1])
        print(f"Top {args.top} traders:")
        heap = []
        for account, dollar in per_signer_dollar.items():
            heap.append((-dollar, account))
        heapq.heapify(heap)
        for i in range(min(args.top, len(heap))):
            neg_dollar, account = heapq.heappop(heap)
            print(f"{account} made ${-neg_dollar}")


if __name__ == "__main__":
    main()

