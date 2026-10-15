# USAGE: python3 sodar_downloader.py PROJECT_NAME
#        (use --projects as PROJECT_NAME to get list of all available projects instead)
#
# WARNING: There can only be one active download per folder at any time.
#
# SETUP: 
# Change the relevant options in 'Authorization' section. You will need to create a SODAR API token. 
# Change 'Download_Path' in 'User Options' to wherever you want the downloads to go to.
# Also set an email adress if you want to be notified of failed downloads.

import requests
import os
import yaml
from time import sleep
import sys
import subprocess
import csv
from io import StringIO
from pathlib import Path


### Authorization ###
sodar_url = 'https://sodar.bihealth.org/' # Your SODAR Server
user_uuid = '' # Your user UUID: See the User Profile in top right corner
api_token = '' # Your API token: Create in SODAR in top right corner
category_uuid = '' # Your Lab uuid: On SODAR click on your lab category, then copy uuid from url


### User Options ###
Download_Path = "" # Where to download to
Mail = '' # Set an Email if you want to get notifications on failed jobs. Otherwise leave blank
Max_mem = '64G' # Memory to allocate for the download 
'''
Default memory of 64 is overkill, but big samples crash otherwise. Likely a bug in the -K checksum option of the
current irods version. Maybe wait for next irods update and then change this to a more sensible 8G.
'''

## Headers (Only touch this if your SODER server is not the BIH one) ##
auth_header = {'Authorization': 'token {}'.format(api_token)}
project_headers = {**auth_header, 'Accept': 'application/vnd.bihealth.sodar-core.projectroles+json; version=2.0'}
sheet_headers = {**auth_header, 'Accept': 'application/vnd.bihealth.sodar.samplesheets+json; version=1.2'}
zone_headers = {**auth_header, 'Accept': 'application/vnd.bihealth.sodar.landingzones+json; version=1.1'}



def get_all_projects():
    url = f'{sodar_url}/project/api/list'
    projects = requests.get(url, headers=project_headers).json()
    projects_dict = {p['title'] : p['sodar_uuid'] for p in projects}
    return projects_dict

def get_sample_names(project_uuid):
    url = f'{sodar_url}/samplesheets/api/export/json/{project_uuid}'
    response_data = requests.get(url, headers=sheet_headers).json()
    assays = response_data['assays']
    assays = next(iter(assays.values()))
    tsv = next(iter(assays.values()))
    reader = csv.DictReader(StringIO(tsv), delimiter="\t")
    samples = [row["Library Name"] for row in reader]
    return samples

def get_assay_irods(project_uuid):
    url = f'{sodar_url}samplesheets/api/investigation/retrieve/{project_uuid}'
    response_data = requests.get(url, headers=sheet_headers).json()
    study = next(iter(response_data["studies"].values()))
    assays = next(iter(study["assays"].values()))
    return(assays["irods_path"])




if __name__ == "__main__":

    #Check if irods is initiated
    irods_check = subprocess.run(
        ["ils"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    if irods_check.returncode != 0:
        print("Irods authentication required. Run 'iinit', then rerun this script again.")
        sys.exit(1)

    #Get SODAR INFO
    if len(sys.argv) != 2:
        print("No project name specified")
        quit()
    p_name = sys.argv[1]
    try:
        all_p = get_all_projects()
    except:
        print("Failed to get list of your projects. Your API key is likely out of date")
        quit()
    if p_name not in all_p.keys() or p_name == '--projects':
        print("Project not found. Available Projects:")
        print(all_p.keys())
        quit()
    assay_path = get_assay_irods(all_p[p_name])
    p_uuid = all_p[p_name]
    samples = get_sample_names(p_uuid)

    #Select Samples
    print("Available samples:")
    for i,s in enumerate(samples):
        print(f'{str(i+1)} : {s}')
    inp = input("Enter samples to download, separated by commas. E.g '1,5,12,20'."
                "Enter 0 to download all. Use e.g 4-7 to select samples 4,5,6,7. ")
    if inp == "0":
        selected = list(range(1,len(samples)+1))
    else:
        selected = []
        for x in inp.split(","):
            if "-" in x:
                start, end = map(int, x.split("-"))
                selected.extend(range(start, end + 1))
            else:
                selected.append(int(x))

    #Create slurm command
    p_name = p_name.replace(" ", "_")
    folder = Path(os.path.join(Download_Path,p_name))
    folder.mkdir(parents = True, exist_ok=True)
    status_file = os.path.join(folder,p_name)
    if os.path.exists(status_file + ".running"):
        print("There is already a download process for this folder, wait for this to finish")
        sys.exit()
    commands = ["#!/bin/bash",
        "set -euo pipefail",
        f'rm -f {os.path.join(folder,p_name + ".finish")}',
        f'rm -f {os.path.join(folder,p_name + ".failed")}',
        f'touch {os.path.join(folder,p_name + ".running")}',
        "trap 'rm -f " + status_file + ".running; touch "+ status_file +".failed' ERR"""]
    for s in selected:
        Sample_name = samples[s-1]
        Irods_path = f'i:{assay_path}/{Sample_name}'
        Dest_path = os.path.join(Download_Path, p_name, Sample_name)
        command = f'irsync -r -a -K {Irods_path} {Dest_path}'
        commands.append(command)
    commands.append('chmod -R ug+rwx * 2>/dev/null || true')
    commands.append(f'rm -f {status_file}.running')
    commands.append(f'touch {status_file}.finish')
    commands.append("trap - ERR")
    script = "\n".join(commands)

    slurm_command = ["sbatch",
            f'--mem={Max_mem}', 
            f'--output={os.path.join(Download_Path,p_name,"slurm-%j.out")}'
            ]
    if Mail != '':
        slurm_command.extend(["--mail-type=FAIL", f'--mail-user={Mail}'])

    #Execute Command
    subprocess.run(
        slurm_command,
        input=script,
        text=True,
        check=True,
        )
    print(f'Downloading to {os.path.join(Download_Path,p_name)}. Download is done once {p_name}.finish appears')





