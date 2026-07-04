pragma solidity ^0.4.25;


contract SmartexInvoice  {

    function advSend(address _to, uint _value, bytes _data){
         _to.call.value(_value)(_data);
    }
}
