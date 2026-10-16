import type {ReactNode} from 'react';
export function TaskCardBody({children,actions}:{children:ReactNode;actions:ReactNode}) {
 return <div className="xy-task-card-body"><div className="xy-task-card-scroll" tabIndex={0}>{children}</div><footer className="xy-task-card-actions">{actions}</footer></div>;
}
