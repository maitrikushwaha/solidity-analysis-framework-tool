pragma solidity ^0.4.25;


contract SharkProxy{

    function forward(address _destination, uint256 _value, bytes _data) {
        assert(_destination.call.value(_value)(_data));
    }
}
