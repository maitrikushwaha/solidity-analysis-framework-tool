// For verification only just change uint256 to uint8 and thus tool detect "Underflow Detected for state variable balanceOf at node ExpressionStatement_1!"
pragma solidity ^0.4.10;

contract IntegerOverflowAdd {
    mapping (address => uint8) public balanceOf;

    // INSECURE
    function transfer(address _to, uint8 _value) public{
        /* Check if sender has balance */
        require(balanceOf[msg.sender] >= _value);
        balanceOf[msg.sender] = balanceOf[msg.sender] - _value;
        // <yes> <report> ARITHMETIC
        balanceOf[_to] =balanceOf[_to] +  _value;
}
}