# Discord-Server-Dumper
A bot to Backup or Arcive a Discord Server

   
 This Script is a Discord bot That can be used to Backup a whole Discord server.  
   
**It is not the cleanest code and certainly not the most efficient, however it gets the job done**.  
Also note that somtimes you may find some german in between!
Normally I don't publish my scripts but someone requested it. 

**Important notes:** 

Please note that it saves the token in plain text in the config folder.  
Each channel will be saved in an **HTML** file.  
   
**Attachments** will be saved and shown if the  **HTML** file is opened in a browser.  
   
 Please note that I am not a web developer and only did some basic optimization.  

**Bigger Discord servers** can sometimes cause  **crashes**; if that happens, simply restart the bot.  
 I implemented that if a channel got archived successfully, it will be saved in a .json, so you don't have to redo the whole thing.

Dont question why, **but to show the Name of the user (not ther ID) you have to use the add_role Command.**  
 if you want it all to be shown just add the @everyone role  

Lastly, older servers and more active servers need more drive space. Please keep that in mind.

**How to Run:**  
Simply run the script; you will be requested for a Bot Token in the terminal.  
   
 Simply copy and paste yours into the Terminal. The token will then be saved.

**Commands** **:**  
/dump_server (Archive all channels in the server (Main Command))  
/archive  (Archive only the current channel)   
/add_role (Adds a role that will be named in the HTML)  
/delt_role (Delete a role that will be named in the HTML)  
/show_role  (Show roles that will be named in the HTML)  
   
   

Results then will be found in the Archive folder inside the bots folder.

**Side notes:**  
I also implemented detection for if the same attachment is posted multiple times; it only saves it once.  
I created a base structure so you can browse the channels all in your browser.  
   
 For that, click on the index.html in the backups main folder.  
If you need any changes feel free to fork. (credits aprricated)  

if you have questions feel free to contact me on discord: lhw_1221
pls note however that it is months since i wrote this.