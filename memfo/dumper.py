""" For dumping data to .csv """

import csv
from datetime import datetime

def dump_to_csv(infos):
    """
    Dumps all historical sample data (self.infos) to /tmp/memfo.csv.

    The CSV format uses the following columns:
    1. Wall Clock Timestamp (ISO Format)
    2. Report relative time (int)
    3. All other keys from the sample dictionary (data assumed to be in Bytes/B)
    """

    filename = "/tmp/memfo.csv"
    if not infos:
        return ''

    # --- 1. Define Header and Keys ---
    # Get all keys from the first sample. Assuming all samples have the same keys.
    data_keys = list(infos[0].keys())

    # --- 2. Prepare Data Rows ---
    data_rows = []

    for sample in reversed(infos):
        # Convert the internal wall-clock timestamp (seconds since epoch) to ISO format
        # Use UTC for consistency across environments
        row = []

        # Append the raw data values based on the data_keys order
        for key in data_keys:
            value = sample.get(key, 0)
            if key == '_time':
                value = datetime.utcfromtimestamp(value).isoformat()
            row.append(value) # Use .get() for safety
        data_rows.append(row)

    # --- 3. Write to CSV File ---
    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            # Write the header
            writer.writerow(data_keys)
            # Write the data rows
            writer.writerows(data_rows)

        # Provide success feedback
        num_samples = len(data_rows)
        return f"Dumped {num_samples} samples to {filename} (Units: Bytes)."

    except IOError as e:
        return f"Dump failed: Cannot write to {filename}. Error: {e}"
