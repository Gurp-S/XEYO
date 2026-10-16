import {Component, type ReactNode} from 'react';

export class PanelErrorBoundary extends Component<{children:ReactNode;name:string;resetKey?:string}, {failed:boolean}> {
	state={failed:false};
	static getDerivedStateFromError() {return {failed:true};}
	componentDidCatch(error: Error) {console.error(`[${this.props.name}]`,error);}
	componentDidUpdate(previous:Readonly<{resetKey?:string}>) {if(previous.resetKey!==this.props.resetKey&&this.state.failed)this.setState({failed:false});}
	render() {return this.state.failed ? <div role="alert" className="xy-panel-error"><p>{this.props.name}暂时无法显示。</p><button onClick={()=>this.setState({failed:false})}>重新打开</button></div> : this.props.children;}
}
