from scrapers.utils.google_sheet_events import sync_csv_to_sheet

if __name__ == "__main__":
    sync_csv_to_sheet("csv_events/misonoza.csv", "御園座")
    print("Synced csv_events/misonoza.csv to 御園座 sheet")