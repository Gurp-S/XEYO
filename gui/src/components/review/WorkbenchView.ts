import {createContext} from 'react';

export const WorkbenchView = createContext({
 split:false, expanded:false, toggleSplit:()=>{}, toggleExpanded:()=>{},
 closeFile:async()=>false,
 registerFileClose:(_handler:(()=>Promise<boolean>) | null)=>{},
});
