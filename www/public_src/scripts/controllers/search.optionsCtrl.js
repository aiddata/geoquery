angular.module('aiddataDET')
.controller('OptionsCtrl', function ($scope, $rootScope, $log, $stateParams, queryFactory) {
  $scope.dataset = {};

  $scope.options = [
    {
      name: 'Extract Options',
      type: 'checkbox',
      loc: 'options.extract_types',
      dest: 'options.extract_types',
      pick: function(x) { return _.get(x, 'name'); },
      data: []
    },
    {
      name: 'Years',
      type: 'checkbox',
      loc: 'resources',
      dest: 'files',
      pick: function(x) { return _.pick(x, ['name', 'path']); },
      data: []
    }
  ];

  $scope.toggleOption = function (isChecked, val, option) {
    var optionData = option.pick(val);
    var action = isChecked ? queryFactory.toggleOptionOn(option.dest, optionData) :
      queryFactory.toggleOptionOff(option.dest, optionData);

    var direction = val.checked ? 'off' : 'on';

    $rootScope.$broadcast('options:updated', { key: option.dest, value: optionData, direction: direction });
  };

  $scope.getTimeStamp = function (date, format) {
    var timeFormatter = d3.timeFormat('%Y');
    var timeParser = d3.timeParse(format),
        formDate = timeFormatter(timeParser(date));
    return formDate;
  };

  $scope.toggleAll = function (option, isChecked) {
    var checkOn = _.isNil(isChecked) ? option.allChecked : isChecked;
    var updates = _.chain(option)
    .get('data')
    .filter({ checked: checkOn })
    .map(function(o) {
      $scope.toggleOption(!checkOn, o, option);
    })
    .value();
  };

  $scope.showOption = function (option) {
    return !_.size(option.data) ? false :
      option.data.length > 1 ? true :
      !(option.name === 'Years' && _.get($scope.dataset, 'temporal.name') === 'Temporally Invariant');
  };

  $rootScope.$on('dataset:selected', function (e, data) {
    $scope.dataset = data;
  });

  $rootScope.$on('options:updated', function(e, data) {
    var checked = { checked: data.direction === 'on' };
    var search = _.isString(data.value) ? { name: data.value } : data.value;
    var option = _.find($scope.options, { dest: data.key });
    var targetOption = _.chain(option)
      .get('data')
      .find(search)
      .extend(checked)
      .value();
    option.checkedCount = _.chain(option).get('data').filter({ checked: true }).size().value();
    option.allChecked = data.direction === 'off' ? false :
      option.checkedCount === option.data.length;
  });

  $scope.$on('$viewContentLoaded', function (event) {
    $scope.dataset = queryFactory.getDataset($stateParams.dataset);

    _.each($scope.options, function (opt) {
      mapOption(opt);
      if (opt.data.length === 1) {
        $scope.toggleOption(!opt.data[0].checked, opt.data[0], opt);
      }
    });
  });

  function mapOption (option) {
    option.data = _.chain($scope.dataset)
      .get(option.loc)
      .map(function (choice) {
        return _.isString(choice) ? { name: choice } : choice;
      })
      .value();
  }
});
