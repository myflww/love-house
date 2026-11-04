/* A phone opens its owner's service. No credentials or memories leave the local app here. */
export function memoryServiceUrl(value){
 if(typeof value!=='string'||/[\\\s\u0000-\u001f]/.test(value))throw new Error('请输入你自己的完整 HTTPS 服务地址。');
 let url;try{url=new URL(value);}catch{throw new Error('请输入你自己的完整 HTTPS 服务地址。');}
 if(url.protocol!=='https:'||!url.hostname||url.username||url.password||url.search||url.hash||!['','/','/mobile','/mobile/'].includes(url.pathname))throw new Error('服务地址须使用 HTTPS，不能带凭据、查询参数或其他页面路径。');
 return url.origin+'/mobile';
}
