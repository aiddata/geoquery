angular.module('aiddataDET')
.directive('tabWatch', function($window) {
  return {
    require: ['mdTabs'],
    restrict: 'A',
    link: function(scope, l, attrs, controllers) {
      var mdTabsCtrl = controllers[0];
      var origSelectFn = mdTabsCtrl.select;

      // Used to overwrite md-tabs directive function calls
      // In order to place a button in the tab bar
      mdTabsCtrl.select = function(index) {
        if (index) {
          origSelectFn(index);
        } else {
          scope.toggleToolBox();
        }
      };
    }
  };
});
