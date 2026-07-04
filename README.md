# Pantkara Development
This repository contains tools and scripts for Pantkara Organization workflows. This includes tools for importing and analyzing parcels, exporting layouts automatically, and more. The following are the important contents of this repository:
* Parcel analysis and layouts.atbx: The ArcGIS Toolbox that should be loaded into your project. The Toolbox is essentially the user interface that allows you to run scripts through ArcGIS. Those scripts are found in the folder Parcel-analysis-and-layouts
* Parcel-analysis-and-layouts folder: This folder contains the scripts that the Toolbox uses
* Other folder: This folder contains some standalone jupyter notebook scripts. They are also run through through ArcGIS, but those are interactive scripts, they don't require a Toolbox. More details below. 

## Getting the Tools on Your Computer

### What You'll Need

Before downloading the tools, make sure you have **GitHub Desktop** installed. GitHub Desktop is a free application that lets you download and manage files from GitHub without any coding knowledge.

- Download GitHub Desktop from: [desktop.github.com](https://desktop.github.com)
- Install it and sign in (create an account at [github.com](https://github.com) **with your organization email**)

***

### How to Clone (Download) This Repository

"Cloning" simply means downloading a copy of all the tools and files from this repository to your own computer, so you can use and run them locally.

**Step 1 – Open the repository in GitHub Desktop**

On this GitHub page, click the green **"< > Code"** button near the top right of the file list, then select **"Open with GitHub Desktop"**.

<img width="404" height="305" alt="image" src="https://github.com/user-attachments/assets/d25ac4ff-1474-4e8d-aa51-19957d7c8089" />

**Step 2 – Choose where to save the files**

GitHub Desktop will open and ask you where on your computer you'd like to save the repository. Click **"Choose..."** to browse to a folder (for example, `Documents\GIS Tools`), then click **"Clone"**.

<img width="1920" height="1032" alt="image" src="https://github.com/user-attachments/assets/c650ceda-e780-4972-9c18-58d7305020fe" />

**Step 3 – Wait for the download to finish**

GitHub Desktop will download all the files. Once it's done, you'll see the repository listed on the left side of the app.

<img width="647" height="460" alt="image" src="https://github.com/user-attachments/assets/52f2fce2-bf2b-4532-a8b3-b1f3f6050c5a" />

**Step 4 – Find the files on your computer**

To open the folder where all the files were saved, click the **"Show in Explorer"** button (Windows) or **"Reveal in Finder"** (Mac) in GitHub Desktop.

<img width="1008" height="498" alt="image" src="https://github.com/user-attachments/assets/a9db418e-5298-4d51-a380-2d9cc7a66d76" />


***

### Keeping the Tools Up to Date

Whenever new tools or updates are added to this repository, you can get the latest version by opening GitHub Desktop, selecting Repository, and then **"Fetch"** and **Pull**. This will update your local copy without you having to download anything manually.

<img width="383" height="456" alt="image" src="https://github.com/user-attachments/assets/5909adc5-d631-4b5f-9517-75baf3774cd2" />


## Setting up the Tools
The **Development** folder in which you have cloned this repository in your local computer **should be a stable folder**. The tools will reside there, and ArcGIS will read them from there. Copy the Folder path and use "Add folder Connection" from Catalog, to import them in the project.

<img width="493" height="86" alt="image" src="https://github.com/user-attachments/assets/0a0d5e51-2ec3-4cca-b492-a0b648f2657f" /> 

Then you should be able to see the tools enlisted in your project. After saving the project, the folder (and thus the tools) will now always be accessible. 

<img width="525" height="581" alt="image" src="https://github.com/user-attachments/assets/c69768ba-ab84-442e-b25b-63041022ef74" />



